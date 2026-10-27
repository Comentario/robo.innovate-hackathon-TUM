#include "BrickflowStage.h"
#include "FilmTiming.h"
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
template<class Phase> double End(const Phase& S){return S.Start+brickflow::film::elapsed(double(S.Count)/FPS,double(S.Count)/FPS,S.Rate0,S.Rate1);}
}

double ABrickflowStage::FilmNativeTime(double VideoSeconds) const
{
    for(const auto& S:FilmShots){
        if(VideoSeconds<double(S.First+S.Count)/FPS)
            return S.Start+brickflow::film::elapsed(double(S.Count)/FPS,VideoSeconds-double(S.First)/FPS,S.Rate0,S.Rate1);
    }
    return End(FilmShots.Last());
}

void ABrickflowStage::BuildFilmPlan()
{
    FilmAccepted=Model->named("9568");FilmRejected=Model->named("9567");
    const auto& A=Model->records[FilmAccepted];const auto& B=Model->records[FilmRejected];
    if(!A.good||B.good||A.layer!=19||B.layer!=19||A.c!=B.c||A.j!=B.j||A.row!=B.row)
        throw std::runtime_error("Film subjects no longer match the frozen reference");
    bool Shipped=false;for(const auto& P:Model->pallets)for(int ID:P.ids)if(ID==FilmAccepted)Shipped=true;
    if(!Shipped)throw std::runtime_error("Film subject is absent from completed output");
    auto Now=[&]{return FilmShots.IsEmpty()?0.:End(FilmShots.Last());};
    auto VideoNow=[&]{return FilmShots.IsEmpty()?0.:double(FilmShots.Last().First+FilmShots.Last().Count)/FPS;};
    auto Add=[&](const FString& Name,int32 Count,double R0,double R1,const FString& Tag=TEXT("continuous")){
        if(Count<=0)return;
        FFilmShot S;S.Name=Name;S.View=Tag;S.First=FMath::RoundToInt(VideoNow()*FPS);S.Count=Count;S.Subject=FilmAccepted;
        S.Start=Now();S.Rate0=R0;S.Rate1=R1;S.Freeze=R0==0&&R1==0;FilmShots.Add(S);
    };
    auto NormalTo=[&](const FString& Name,double Target){Add(Name,FMath::RoundToInt((Target-Now())*FPS),1,1);};
    auto Grid=[](double T){return FMath::CeilToDouble(T*FPS)/FPS;};
    const double RowStart=Event(A,"raise-six-rows-each-side").start;
    const double RowHold=Grid(Event(A,"place-six-rows-on-v1").end)+1.2;
    const double ScanStart=Event(A,"inspection-entry").start;
    const double SensorHold=Grid(ScanStart+5);
    const double RejectEnd=Event(B,"supported-reject-decline").end+1.5;
    const double StackStart=Grid(Event(A,"push-complete-row").end)+2;
    const double Outfeed=Event(A,"finished-pallet-outfeed").start;
    const double OutputEnd=Event(A,"lower-pallet-on-transport-cart").end;
    NormalTo(TEXT("Input pallets, dehacking and row transfer"),RowHold-1);
    Add(TEXT("Ease to Franka comparison"),60,1,0);
    const double RowHoldVideo=VideoNow();Add(TEXT("Franka profile insertion handle"),150,0,0,TEXT("row-hold"));
    const double RowResumeVideo=VideoNow();Add(TEXT("Ease back to production"),60,0,1);
    NormalTo(TEXT("Follow to inspection"),SensorHold-1);
    Add(TEXT("Ease to inspection comparison"),60,1,0);
    const double SensorHoldVideo=VideoNow();Add(TEXT("Detection algorithm insertion handle"),210,0,0,TEXT("sensor"));
    const double SensorResumeVideo=VideoNow();Add(TEXT("Ease back to inspection"),60,0,1);
    NormalTo(TEXT("Rejection, routing and row formation"),StackStart);
    const double StackVideo=VideoNow();
    constexpr double Peak=16,Ramp=4;
    const double Target=Grid(Outfeed-3);
    const int32 Plateau=FMath::RoundToInt((Target-Now()-Ramp*(1+Peak))/Peak*FPS);
    if(Plateau<0)throw std::runtime_error("Insufficient assembly interval for continuous speed ramps");
    Add(TEXT("Smooth assembly acceleration"),120,1,Peak);
    Add(TEXT("Continuous pallet reconstruction"),Plateau,Peak,Peak);
    Add(TEXT("Smooth return to transport speed"),120,Peak,1);
    NormalTo(TEXT("Output outfeed, lift, bridge and deposit at real speed"),Grid(OutputEnd)+2);
    FilmRevealAt=VideoNow();
    Add(TEXT("Pullback with smooth timelapse acceleration"),240,1,40,TEXT("reveal"));
    Add(TEXT("Wide continuous factory timelapse"),1200,40,40,TEXT("reveal"));
    if(End(FilmShots.Last())>Model->total)throw std::runtime_error("Film exceeds the native batch");
    auto AtNative=[&](double T){
        double Lo=0,Hi=double(FilmShots.Last().First+FilmShots.Last().Count)/FPS;
        for(int I=0;I<70;++I){double Mid=(Lo+Hi)/2;if(FilmNativeTime(Mid)<T)Lo=Mid;else Hi=Mid;}
        return (Lo+Hi)/2;
    };
    FilmCues.Add({0,0,TEXT("input")});
    FilmCues.Add({AtNative(29),4,TEXT("dehack")});
    FilmCues.Add({AtNative(Event(A,"place-on-loading-belts").end),6,TEXT("follow")});
    FilmCues.Add({AtNative(RowStart-6),6,TEXT("row-profile")});
    FilmCues.Add({RowResumeVideo,6,TEXT("follow")});
    FilmCues.Add({AtNative(ScanStart-5),5,TEXT("inspection")});
    FilmCues.Add({AtNative(SensorHold-3),4,TEXT("sensor")});
    FilmCues.Add({SensorResumeVideo,3,TEXT("reject")});
    FilmCues.Add({AtNative(RejectEnd),3,TEXT("follow")});
    FilmCues.Add({AtNative(Event(A,"thirty-position-distribution").start-4),5,TEXT("formation")});
    FilmCues.Add({StackVideo-3,8,TEXT("stacking")});
    FilmCues.Add({AtNative(Outfeed-5),6,TEXT("dispatch")});
    FilmCues.Add({FilmRevealAt,6,TEXT("reveal")});
    for(int32 I=1;I<FilmCues.Num();++I)if(FilmCues[I].At<FilmCues[I-1].At+FilmCues[I-1].Blend-1e-6)
        throw std::runtime_error("Overlapping camera transitions");
    auto Manifest=MakeShared<FJsonObject>();Manifest->SetStringField(TEXT("schema"),TEXT("brickflow.continuous-film.v2"));Manifest->SetBoolField(TEXT("cameraAuditOnly"),FParse::Param(FCommandLine::Get(),TEXT("BrickflowFilmAudit")));
    Manifest->SetStringField(TEXT("referenceSha256"),Asset->GetStringField(TEXT("referenceSha256")));
    Manifest->SetNumberField(TEXT("fps"),FPS);Manifest->SetNumberField(TEXT("frames"),FilmShots.Last().First+FilmShots.Last().Count);
    Manifest->SetNumberField(TEXT("durationSeconds"),VideoNow());Manifest->SetNumberField(TEXT("nativeEnd"),Now());
    Manifest->SetStringField(TEXT("acceptedId"),UTF8_TO_TCHAR(A.id.c_str()));Manifest->SetStringField(TEXT("rejectedId"),UTF8_TO_TCHAR(B.id.c_str()));
    Manifest->SetStringField(TEXT("motion"),TEXT("Continuous native clock from input delivery; no skips. Smooth speed ramps, assembly 16x, bridge 1x, final 40x."));
    Manifest->SetStringField(TEXT("limitations"),TEXT("Original synthetic classifier and kinematic mechanisms. Profile aligned to the reference viewing plane, not calibrated to measured physical-camera intrinsics."));
    TArray<TSharedPtr<FJsonValue>> Phases;
    for(const auto& S:FilmShots){auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("name"),S.Name);J->SetStringField(TEXT("camera"),S.View);
        J->SetNumberField(TEXT("firstFrame"),S.First);J->SetNumberField(TEXT("frames"),S.Count);J->SetNumberField(TEXT("nativeStart"),S.Start);
        J->SetNumberField(TEXT("nativeEnd"),End(S));J->SetNumberField(TEXT("rateStart"),S.Rate0);J->SetNumberField(TEXT("rateEnd"),S.Rate1);
        J->SetBoolField(TEXT("freeze"),S.Freeze);Phases.Add(MakeShared<FJsonValueObject>(J));}
    TArray<TSharedPtr<FJsonValue>> Cues;
    for(const auto& C:FilmCues){auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("view"),C.View);J->SetNumberField(TEXT("atSeconds"),C.At);J->SetNumberField(TEXT("blendSeconds"),C.Blend);Cues.Add(MakeShared<FJsonValueObject>(J));}
    Manifest->SetArrayField(TEXT("shots"),Phases);Manifest->SetArrayField(TEXT("cameraCues"),Cues);
    const auto Before=Model->metrics(FilmNativeTime(FilmRevealAt)),After=Model->metrics(Now());
    Manifest->SetNumberField(TEXT("timelapseAdditionalInspections"),After.inspected-Before.inspected);
    if(After.inspected-Before.inspected<2000)throw std::runtime_error("Final timelapse does not demonstrate thousands of inspections");
    Manifest->SetNumberField(TEXT("rowHoldSeconds"),RowHoldVideo);Manifest->SetNumberField(TEXT("sensorHoldSeconds"),SensorHoldVideo);
    FString Encoded;FJsonSerializer::Serialize(Manifest,TJsonWriterFactory<>::Create(&Encoded));
    FFileHelper::SaveStringToFile(Encoded,*(FilmDirectory/TEXT("edit-plan.json")));
    FFileHelper::SaveStringToFile(TEXT("frame,shot,nativeSeconds,subject,brickX,brickY,brickZ,cameraX,cameraY,cameraZ,lookX,lookY,lookZ,fov,speed,inspected\n"),*(FilmDirectory/TEXT("trace.csv")));
    int32 Port=0;FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmPort="),Port);
    if(Port){auto* System=ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);FilmSocket=System->CreateSocket(NAME_Stream,TEXT("BrickflowFilm"),false);
        auto Address=System->CreateInternetAddr();bool Valid=false;Address->SetIp(TEXT("127.0.0.1"),Valid);Address->SetPort(Port);int32 Actual=0;FilmSocket->SetSendBufferSize(32*1024*1024,Actual);
        if(!FilmSocket->Connect(*Address))throw std::runtime_error("Could not connect native frame encoder");
        FilmScreenshotDelegate=UGameViewportClient::OnScreenshotCaptured().AddUObject(this,&ABrickflowStage::CaptureFilmPixels);}
    bFilmReady=true;
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_CONTINUOUS_FILM frames=%d seconds=%.3f nativeEnd=%.3f additionalInspections=%d"),FilmShots.Last().First+FilmShots.Last().Count,VideoNow(),Now(),After.inspected-Before.inspected);
}

void ABrickflowStage::ApplyFilmFrame(int32 Frame)
{
    const double V=double(Frame)/FPS;
    int32 Phase=0;for(int32 I=0;I<FilmShots.Num();++I)if(Frame>=FilmShots[I].First)Phase=I;
    const auto& S=FilmShots[Phase];Time=FilmNativeTime(V);
    if(!FParse::Param(FCommandLine::Get(),TEXT("BrickflowFilmAudit")))UpdateScene(true);
    auto Focus=[&](int ID){
        FVector P=FVector::ZeroVector;double Sum=0;
        for(int I=-12;I<=12;++I){const double Dt=I/24.,W=FMath::Exp(-.5*Dt*Dt/(.18*.18));
            P+=World(Model->pose(ID,FilmNativeTime(FMath::Max(0.,V+Dt))))*W;Sum+=W;}
        return P/Sum;
    };
    const FVector A=Focus(FilmAccepted),B=Focus(FilmRejected);
    const auto& AR=Model->records[FilmAccepted];const auto& Row=Event(AR,"raise-six-rows-each-side");
    const double Side=(Row.from[2]+Event(AR,"place-six-rows-on-v1").to[2])/2*100;
    struct View {FVector Position,Look;double FOV;};
    auto Evaluate=[&](const FString& Mode)->View{
        FVector Look=A+FVector(0,0,22),Offset(170,-330,230);double FOV=70;
        if(Mode==TEXT("input")){Look=Focus(Model->named("input-cart"))+FVector(0,0,110);Offset=FVector(950,-600,280);}
        else if(Mode==TEXT("dehack")){Look=A+FVector(0,0,25);Offset=FVector(600,450,240);FOV=65;}
        else if(Mode==TEXT("row-profile")){Look=FVector(2150,Side,165);Offset=FVector(620,-80,120);FOV=55;}
        else if(Mode==TEXT("inspection")){Look=FVector(2800,-700,160);Offset=FVector(130,-370,220);}
        else if(Mode==TEXT("sensor")){
            double HoldAt=0;for(const auto& P:FilmShots)if(P.View==TEXT("sensor"))HoldAt=double(P.First)/FPS;
            const double U=brickflow::film::blend((V-HoldAt)/7);Look=FVector(2810,-700,192);Offset=FVector(100,-205,110).RotateAngleAxis(75*U,FVector::UpVector);
        }else if(Mode==TEXT("reject")){Look=B+FVector(0,0,22);Offset=FVector(160,-310,230);}
        else if(Mode==TEXT("formation")){Offset=FVector(280,-380,270);}
        else if(Mode==TEXT("stacking")){Look=FVector(5100,-700,160);Offset=FVector(1000,450,240);}
        else if(Mode==TEXT("dispatch")){Look=A+FVector(0,0,67);Offset=FVector(450,70,200);}
        else if(Mode==TEXT("reveal")){
            const double Elapsed=V-FilmRevealAt;const FVector Center(2600,0,0),Wide=Center+FVector(7400*FMath::Cos(.82),7400*FMath::Sin(.82),7500);
            if(Elapsed<=16){const double U=brickflow::film::blend(Elapsed/16);const FVector Near=A+FVector(0,0,67);
                return {FMath::Lerp(Near+FVector(450,70,200),Wide,U),FMath::Lerp(Near,Center,U),70};}
            const double Angle=.82+2*PI*brickflow::film::blend((Elapsed-16)/32);
            return {Center+FVector(7400*FMath::Cos(Angle),7400*FMath::Sin(Angle),7500),Center,70};
        }else{
            const double U=brickflow::film::smooth((A.X-2600)/400);Offset=FMath::Lerp(FVector(220,380,230),FVector(170,-330,230),U);
        }
        return {Look+Offset,Look,FOV};
    };
    int32 Cue=0;for(int32 I=0;I<FilmCues.Num();++I)if(V>=FilmCues[I].At)Cue=I;
    View Desired=Evaluate(FilmCues[Cue].View);
    if(Cue>0){const auto Old=Evaluate(FilmCues[Cue-1].View);const double U=brickflow::film::blend((V-FilmCues[Cue].At)/FilmCues[Cue].Blend);
        const FVector OA=Old.Position-Old.Look,OB=Desired.Position-Desired.Look;
        const double RadiusA=OA.Length(),RadiusB=OB.Length();const FVector DA=OA/RadiusA,DB=OB/RadiusB;
        const double Angle=FMath::Acos(FMath::Clamp(FVector::DotProduct(DA,DB),-1.,1.));
        const FVector Direction=Angle<1e-7?DA:(DA*FMath::Sin((1-U)*Angle)+DB*FMath::Sin(U*Angle))/FMath::Sin(Angle);
        const FVector Target=FMath::Lerp(Old.Look,Desired.Look,U);
        Desired={Target+Direction*FMath::Lerp(RadiusA,RadiusB,U),Target,FMath::Lerp(Old.FOV,Desired.FOV,U)};}
    FilmExtraSettle=0;CameraBlend=1;CameraLookTarget=Desired.Look;CameraTarget=Desired.Position;
    Camera->SetWorldLocation(Desired.Position);Camera->SetWorldRotation((Desired.Look-Desired.Position).Rotation());Camera->SetFieldOfView(Desired.FOV);
    const int Subject=FilmCues[Cue].View==TEXT("reject")?FilmRejected:FilmAccepted;
    const auto P=Model->pose(Subject,Time);const double Rate=brickflow::film::speed(double(S.Count)/FPS,V-double(S.First)/FPS,S.Rate0,S.Rate1);
    FString Line=FString::Printf(TEXT("%d,%d,%.12f,%s,%.12f,%.12f,%.12f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.8f,%.8f,%d\n"),Frame,Phase,Time,
        UTF8_TO_TCHAR(Model->records[Subject].id.c_str()),P[0],P[1],P[2],Desired.Position.X,Desired.Position.Y,Desired.Position.Z,Desired.Look.X,Desired.Look.Y,Desired.Look.Z,Desired.FOV,Rate,Model->metrics(Time).inspected);
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
    if(!bFilmReady){
        BuildFilmPlan();
        if(FParse::Param(FCommandLine::Get(),TEXT("BrickflowFilmAudit"))){
            for(int32 F=0;F<FilmShots.Last().First+FilmShots.Last().Count;++F)ApplyFilmFrame(F);
            FFileHelper::SaveStringToFile(TEXT("camera audit only\n"),*(FilmDirectory/TEXT("audit.status")));
            FPlatformMisc::RequestExit(false);FilmDirectory.Empty();return;
        }
        ApplyFilmFrame(FilmFrame);FilmSettle=1;
    }
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
