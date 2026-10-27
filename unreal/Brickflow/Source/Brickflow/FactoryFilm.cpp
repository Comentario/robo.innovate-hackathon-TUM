#include "BrickflowStage.h"
#include "Camera/CameraComponent.h"
#include "Engine/GameViewportClient.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "UnrealClient.h"
#include "Sockets.h"
#include "SocketSubsystem.h"
#include "IPAddress.h"
#include "Serialization/JsonSerializer.h"

namespace {
constexpr int32 FPS=30;
FVector World(const brickflow::Pose& P){return FVector(P[0],P[2],P[1])*100;}
const brickflow::Track& Event(const brickflow::Record& R,std::string_view Kind){
    for(const auto& T:R.tracks)if(T.kind==Kind)return T;
    throw std::runtime_error("Film subject is missing required event: "+std::string(Kind));
}
}
void ABrickflowStage::BuildFilmPlan()
{
    FilmAccepted=Model->named("9568");FilmRejected=Model->named("9567");
    const auto& A=Model->records[FilmAccepted];const auto& B=Model->records[FilmRejected];
    if(!A.good||B.good||A.layer!=19||B.layer!=19||A.c!=B.c||A.j!=B.j||A.row!=B.row)
        throw std::runtime_error("Film subject identities no longer match frozen reference");
    bool Shipped=false;for(const auto& P:Model->pallets)for(int ID:P.ids)if(ID==FilmAccepted)Shipped=true;
    if(!Shipped)throw std::runtime_error("Film subject is not in a complete output pallet");
    auto Add=[&](const FString& Name,const FString& View,int ID,double Start,double Duration,bool Freeze=false){
        int32 First=FilmShots.IsEmpty()?0:FilmShots.Last().First+FilmShots.Last().Count;
        FilmShots.Add({Name,View,First,FMath::Max(1,FMath::RoundToInt(Duration*FPS)),ID,Start,Freeze});
    };
    const double RowStart=Event(A,"raise-six-rows-each-side").start;
    const double RowEnd=Event(A,"place-six-rows-on-v1").end;
    const double ScanStart=Event(A,"inspection-entry").start;
    const double RejectEnd=Event(B,"supported-reject-decline").end+1.5;
    const double OutputEnd=Event(A,"lower-pallet-on-transport-cart").end;
    const double SourceStart=Event(A,"place-on-loading-belts").end;
    Add(TEXT("Full plant orbit"),TEXT("orbit"),FilmAccepted,SourceStart-16,16);
    auto FollowRange=[&](double Start,double End){
        double Cursor=Start;
        for(const auto& T:A.tracks){
            if(T.end<=Start||T.start>=End)continue;
            const double Lo=FMath::Max(T.start,Start),Hi=FMath::Min(T.end,End);
            if(Lo-Cursor>4){Add(TEXT("Accumulation before edit"),TEXT("follow"),FilmAccepted,Cursor,1.5);Cursor=Lo-1;}
            if(Lo>Cursor)Add(TEXT("Reserved downstream wait"),TEXT("follow"),FilmAccepted,Cursor,Lo-Cursor);
            Add(UTF8_TO_TCHAR(std::string(T.kind).c_str()),TEXT("follow"),FilmAccepted,Lo,Hi-Lo);Cursor=Hi;
        }
        if(End>Cursor)Add(TEXT("End of stage"),TEXT("follow"),FilmAccepted,Cursor,FMath::Min(2.,End-Cursor));
    };
    FollowRange(SourceStart,RowStart-2);
    Add(TEXT("Source layer and row extraction"),TEXT("row"),FilmAccepted,RowStart-2,RowEnd-RowStart+2.5);
    Add(TEXT("Franka insertion handle"),TEXT("row-hold"),FilmAccepted,RowEnd+.5,5,true);
    FollowRange(RowEnd+.5,ScanStart-1);
    Add(TEXT("Accepted brick followed by rejected brick"),TEXT("inspection"),FilmAccepted,ScanStart-1,6);
    Add(TEXT("Detection algorithm insertion handle"),TEXT("sensor"),FilmAccepted,ScanStart+5,7,true);
    Add(TEXT("Actual rejection and supported discard"),TEXT("reject"),FilmRejected,ScanStart+5,RejectEnd-(ScanStart+5));
    FollowRange(RejectEnd,OutputEnd);
    Add(TEXT("Output pallet and full plant reveal"),TEXT("reveal"),FilmAccepted,OutputEnd,12);
    auto Manifest=MakeShared<FJsonObject>();Manifest->SetStringField(TEXT("referenceSha256"),Asset->GetStringField(TEXT("referenceSha256")));
    Manifest->SetNumberField(TEXT("fps"),FPS);Manifest->SetNumberField(TEXT("frames"),FilmShots.Last().First+FilmShots.Last().Count);
    Manifest->SetNumberField(TEXT("durationSeconds"),double(FilmShots.Last().First+FilmShots.Last().Count)/FPS);
    Manifest->SetStringField(TEXT("acceptedId"),UTF8_TO_TCHAR(A.id.c_str()));Manifest->SetStringField(TEXT("rejectedId"),UTF8_TO_TCHAR(B.id.c_str()));
    Manifest->SetStringField(TEXT("motion"),TEXT("Native pose at 1x; fixed native time during camera holds. Idle accumulation may be cut, never retimed."));
    Manifest->SetStringField(TEXT("limitations"),TEXT("Synthetic classifier. Existing mechanisms only. Brick can become physically occluded inside its completed pallet. No generated Franka or detection footage."));
    TArray<TSharedPtr<FJsonValue>> Shots;
    for(const auto& S:FilmShots){auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("name"),S.Name);J->SetStringField(TEXT("camera"),S.View);
        J->SetNumberField(TEXT("firstFrame"),S.First);J->SetNumberField(TEXT("frames"),S.Count);J->SetNumberField(TEXT("nativeStart"),S.Start);
        J->SetNumberField(TEXT("nativeEnd"),S.Start+(S.Freeze?0:double(S.Count-1)/FPS));J->SetBoolField(TEXT("freeze"),S.Freeze);Shots.Add(MakeShared<FJsonValueObject>(J));}
    Manifest->SetArrayField(TEXT("shots"),Shots);FString Encoded;FJsonSerializer::Serialize(Manifest,TJsonWriterFactory<>::Create(&Encoded));
    FFileHelper::SaveStringToFile(Encoded,*(FilmDirectory/TEXT("edit-plan.json")));
    FFileHelper::SaveStringToFile(TEXT("frame,shot,nativeSeconds,subject,brickX,brickY,brickZ,cameraX,cameraY,cameraZ\n"),*(FilmDirectory/TEXT("trace.csv")));
    int32 Port=0;FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmPort="),Port);
    if(Port){
        auto* System=ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);FilmSocket=System->CreateSocket(NAME_Stream,TEXT("BrickflowFilm"),false);
        auto Address=System->CreateInternetAddr();bool Valid=false;Address->SetIp(TEXT("127.0.0.1"),Valid);Address->SetPort(Port);
        int32 Actual=0;FilmSocket->SetSendBufferSize(32*1024*1024,Actual);
        if(!FilmSocket->Connect(*Address))throw std::runtime_error("Could not connect native frame encoder");
        FilmScreenshotDelegate=UGameViewportClient::OnScreenshotCaptured().AddUObject(this,&ABrickflowStage::CaptureFilmPixels);
    }
    bFilmReady=true;
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_FILM frames=%d seconds=%.3f accepted=%s rejected=%s"),FilmShots.Last().First+FilmShots.Last().Count,
        double(FilmShots.Last().First+FilmShots.Last().Count)/FPS,UTF8_TO_TCHAR(A.id.c_str()),UTF8_TO_TCHAR(B.id.c_str()));
}
void ABrickflowStage::ApplyFilmFrame(int32 Frame)
{
    const FFilmShot* Shot=nullptr;int32 Index=0;
    for(int32 I=0;I<FilmShots.Num();++I)if(Frame>=FilmShots[I].First&&Frame<FilmShots[I].First+FilmShots[I].Count){Shot=&FilmShots[I];Index=I;break;}
    if(!Shot)return;
    const double U=double(Frame-Shot->First)/FMath::Max(1,Shot->Count-1),Smooth=U*U*(3-2*U);
    const double PreviousTime=Time;
    Time=Shot->Start+(Shot->Freeze?0:double(Frame-Shot->First)/FPS);UpdateScene(true);
    const auto P=Model->pose(Shot->Subject,Time);FVector Look=World(P)+FVector(0,0,22),Offset(170,-330,230),Position;
    if(Shot->View==TEXT("orbit")){
        const double Angle=.82+2*PI*U;Look=FVector(2600,0,0);Offset=FVector(FMath::Cos(Angle)*7400,FMath::Sin(Angle)*7400,7500);
    }else if(Shot->View==TEXT("row")||Shot->View==TEXT("row-hold")){
        Offset=FVector(300,350,200);Look+=FVector(-20,0,15);
        if(Shot->Freeze)Offset=Offset.RotateAngleAxis(18*Smooth,FVector::UpVector);
    }else if(Shot->View==TEXT("inspection")){
        Look=FVector(2800,-700,160);Offset=FVector(130,-370,220);
    }else if(Shot->View==TEXT("sensor")){
        Look=FVector(2810,-700,192);Offset=FVector(100,-205,110).RotateAngleAxis(75*Smooth,FVector::UpVector);
    }else if(Shot->View==TEXT("reject")){
        Offset=FVector(160,-310,230);
    }else if(Shot->View==TEXT("reveal")){
        FVector StartLook=Look+FVector(0,0,45),Start=StartLook+FVector(450,70,200);
        Look=FMath::Lerp(StartLook,FVector(2600,0,0),Smooth);Position=FMath::Lerp(Start,FVector(7650,5410,7500),Smooth);
    }else{
        const auto* Segment=Model->segment(Shot->Subject,Time);
        if(P[0]<24)Offset=FVector(220,380,230);
        if(Segment&&Segment->kind.find("layer")!=std::string_view::npos)Offset=FVector(430,140,330-Look.Z);
        if(Segment&&Segment->kind.find("pallet")!=std::string_view::npos){Offset=FVector(450,70,200);Look+=FVector(0,0,45);}
    }
    if(Shot->View!=TEXT("reveal"))Position=Look+Offset;
    FilmExtraSettle=Frame==Shot->First&&(FMath::Abs(Time-PreviousTime)>.1||FVector::Distance(Position,Camera->GetComponentLocation())>25)?40:0;
    CameraBlend=1;CameraLookTarget=Look;CameraTarget=Position;Camera->SetWorldLocation(Position);Camera->SetWorldRotation((Look-Position).Rotation());
    FString Line=FString::Printf(TEXT("%d,%d,%.12f,%s,%.12f,%.12f,%.12f,%.6f,%.6f,%.6f\n"),Frame,Index,Time,
        UTF8_TO_TCHAR(Model->records[Shot->Subject].id.c_str()),P[0],P[1],P[2],Position.X,Position.Y,Position.Z);
    FFileHelper::SaveStringToFile(Line,*(FilmDirectory/TEXT("trace.csv")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
}
void ABrickflowStage::CaptureFilmPixels(int32 Width,int32 Height,const TArray<FColor>& Pixels)
{
    if(!FilmSocket||FilmPending.IsEmpty())return;
    const uint8* Data=reinterpret_cast<const uint8*>(Pixels.GetData());int32 Remaining=Pixels.Num()*sizeof(FColor);
    while(Remaining>0){int32 Sent=0;if(!FilmSocket->Send(Data,Remaining,Sent)||Sent<=0){UE_LOG(LogTemp,Fatal,TEXT("Native film encoder disconnected"));return;}Data+=Sent;Remaining-=Sent;}
    bFilmFrameCaptured=true;
}
void ABrickflowStage::TickFilm(float DeltaSeconds)
{
    if(!bFilmReady){BuildFilmPlan();ApplyFilmFrame(FilmFrame);FilmSettle=1;}
    FilmWarmup+=DeltaSeconds;if(FilmWarmup<12)return;
    if(!FilmPending.IsEmpty()){
        if(FilmSocket?!bFilmFrameCaptured:IFileManager::Get().FileSize(*FilmPending)<=100)return;
        FilmPending.Empty();bFilmFrameCaptured=false;FilmFrame+=FilmStride;FilmSettle=0;
    }
    const int32 Total=FilmShots.Last().First+FilmShots.Last().Count;
    if(FilmFrame>=FMath::Min(Total,FilmLast>0?FilmLast:Total)){
        if(FilmSocket){FilmSocket->Close();UGameViewportClient::OnScreenshotCaptured().Remove(FilmScreenshotDelegate);ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(FilmSocket);FilmSocket=nullptr;}
        FFileHelper::SaveStringToFile(TEXT("complete\n"),*(FilmDirectory/TEXT("complete.status")));FPlatformMisc::RequestExit(false);return;
    }
    if(FilmSettle==0)ApplyFilmFrame(FilmFrame);
    int32 Settle=8;FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmSettle="),Settle);
    if(++FilmSettle>=FMath::Max(2,Settle)+FilmExtraSettle){
        FilmPending=FilmDirectory/FString::Printf(TEXT("frame-%06d.png"),FilmFrame);
        FScreenshotRequest::RequestScreenshot(FilmPending,false,false);
    }
}
