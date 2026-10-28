#include "BrickflowStage.h"
#include "FilmTiming.h"
#include "Camera/CameraComponent.h"
#include "Engine/GameViewportClient.h"
#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Sockets.h"
#include "SocketSubsystem.h"
#include "IPAddress.h"
#include "UnrealClient.h"

namespace {
FVector SourceWorld(const TArray<TSharedPtr<FJsonValue>>& A){return FVector(A[0]->AsNumber(),A[2]->AsNumber(),A[1]->AsNumber())*100;}
FVector SourcePoint(const brickflow::replay::Pose& P){return FVector(P[0],P[2],P[1])*100;}
}
double ABrickflowStage::SourceNativeTime(double V,double* Rate) const
{
    const auto& Segments=SourceTour->GetArrayField(TEXT("clock"));
    for(const auto& Value:Segments){const auto S=Value->AsObject();const double Start=S->GetNumberField(TEXT("videoStart")),D=S->GetNumberField(TEXT("duration"));
        if(V<Start+D){const double A=S->GetNumberField(TEXT("rateStart")),B=S->GetNumberField(TEXT("rateEnd"));if(Rate)*Rate=brickflow::film::speed(D,V-Start,A,B);
            return S->GetNumberField(TEXT("nativeStart"))+brickflow::film::elapsed(D,V-Start,A,B);}}
    const auto S=Segments.Last()->AsObject();const double D=S->GetNumberField(TEXT("duration"));if(Rate)*Rate=S->GetNumberField(TEXT("rateEnd"));
    return S->GetNumberField(TEXT("nativeStart"))+brickflow::film::elapsed(D,D,S->GetNumberField(TEXT("rateStart")),S->GetNumberField(TEXT("rateEnd")));
}
ABrickflowStage::FSourceCamera ABrickflowStage::SourceCameraAt(double V) const
{
    const FString Subject=SourceTour->GetStringField(TEXT("subject"));const int32 SubjectID=SourceTimeline->named(TCHAR_TO_UTF8(*Subject));
    auto Focus=[&](const FString& Record){const int32 ID=SourceTimeline->named(TCHAR_TO_UTF8(*Record));FVector Sum=FVector::ZeroVector;double Weight=0;
        for(int J=-3;J<=3;++J){const double Dt=J*.06,W=FMath::Exp(-J*J/4.);Sum+=SourcePoint(SourceTimeline->state(ID,SourceNativeTime(FMath::Max(0.,V+Dt))).pose)*W;Weight+=W;}return Sum/Weight;};
    const auto Views=SourceTour->GetObjectField(TEXT("views"));
    auto Evaluate=[&](const FString& Name)->FSourceCamera{
        auto Definition=Views->GetObjectField(Name);FVector Look;
        if(Definition->HasField(TEXT("look")))Look=SourceWorld(Definition->GetArrayField(TEXT("look")));
        else{const FString Record=Definition->GetStringField(TEXT("focus"));Look=Focus(Record==TEXT("subject")?Subject:Record);}
        if(Definition->HasField(TEXT("lookOffset")))Look+=SourceWorld(Definition->GetArrayField(TEXT("lookOffset")));
        FVector Offset=SourceWorld(Definition->GetArrayField(TEXT("offset")));double Angle=0;
        if(Definition->HasField(TEXT("orbitStart"))){const double T=Definition->GetNumberField(TEXT("orbitStart")),D=Definition->GetNumberField(TEXT("orbitDuration"));
            Angle=360*Definition->GetNumberField(TEXT("orbitTurns"))*brickflow::film::blend((V-T)/D);}
        Offset=Offset.RotateAngleAxis(Angle,FVector::UpVector);
        return {Look+Offset,Look,Definition->GetNumberField(TEXT("fov"))};
    };
    const auto& Cues=SourceTour->GetArrayField(TEXT("cues"));int32 Active=0;
    for(int32 I=0;I<Cues.Num();++I)if(V>=Cues[I]->AsObject()->GetNumberField(TEXT("at")))Active=I;
    const auto Cue=Cues[Active]->AsObject();const FString Name=Cue->GetStringField(TEXT("view"));FSourceCamera Desired=Evaluate(Name);
    if(Active){const auto Previous=Evaluate(Cues[Active-1]->AsObject()->GetStringField(TEXT("view")));
        const double U=brickflow::film::blend((V-Cue->GetNumberField(TEXT("at")))/Cue->GetNumberField(TEXT("blend")));
        const FVector A=Previous.P-Previous.Look,B=Desired.P-Desired.Look;const double RA=A.Length(),RB=B.Length();
        const FVector DA=A/RA,DB=B/RB;const double Angle=FMath::Acos(FMath::Clamp(FVector::DotProduct(DA,DB),-1.,1.));
        const FVector Direction=Angle<1e-8?DA:(DA*FMath::Sin((1-U)*Angle)+DB*FMath::Sin(U*Angle))/FMath::Sin(Angle);
        const FVector Look=FMath::Lerp(Previous.Look,Desired.Look,U);Desired={Look+Direction*FMath::Lerp(RA,RB,U),Look,FMath::Lerp(Previous.FOV,Desired.FOV,U)};
    }
    Desired.Name=Name;return Desired;
}
void ABrickflowStage::ApplySourceFrame(int32 Frame)
{
    const double V=double(Frame)/30;double Rate=0;Time=SourceNativeTime(V,&Rate);if(!bSourceAudit)UpdateSourceScene();
    const auto Desired=SourceCameraAt(V);UpdateSourceEnclosures(V);
    const FString Subject=SourceTour->GetStringField(TEXT("subject"));const int32 SubjectID=SourceTimeline->named(TCHAR_TO_UTF8(*Subject));
    CameraBlend=1;CameraTarget=Desired.P;CameraLookTarget=Desired.Look;
    Camera->SetWorldLocation(Desired.P);Camera->SetWorldRotation((Desired.Look-Desired.P).Rotation());Camera->SetFieldOfView(Desired.FOV);
    const auto State=SourceTimeline->state(SubjectID,Time);const auto& P=State.pose;
    FString Line=FString::Printf(TEXT("%d,%.12f,%.9f,%s,%.12f,%.12f,%.12f,%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%s,%.9f,%.9f\n"),
        Frame,Time,Rate,*Subject,P[0],P[1],P[2],State.visible?1:0,Desired.P.X,Desired.P.Y,Desired.P.Z,Desired.Look.X,Desired.Look.Y,Desired.Look.Z,Desired.FOV,*Desired.Name,SourceInspectionCoverage,SourceRoutingCoverage);
    FFileHelper::SaveStringToFile(Line,*(SourceOutput/TEXT("trace.csv")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
}
void ABrickflowStage::TickSourceReplay(float DeltaSeconds)
{
    if(!bFilmReady){
        bFilmReady=true;
        if(bSourceAudit){for(int32 F=SourceFrame;F<SourceEnd;++F)ApplySourceFrame(F);FFileHelper::SaveStringToFile(TEXT("camera audit complete\n"),*(SourceOutput/TEXT("audit.status")));FPlatformMisc::RequestExit(false);return;}
        int32 Port=0;FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmPort="),Port);
        if(Port){auto* System=ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);FilmSocket=System->CreateSocket(NAME_Stream,TEXT("SourceReplayFilm"),false);
            auto Address=System->CreateInternetAddr();bool Valid=false;Address->SetIp(TEXT("127.0.0.1"),Valid);Address->SetPort(Port);int32 Actual=0;FilmSocket->SetSendBufferSize(32*1024*1024,Actual);
            if(!FilmSocket->Connect(*Address))throw std::runtime_error("Source frame encoder connection failed");
            FilmScreenshotDelegate=UGameViewportClient::OnScreenshotCaptured().AddUObject(this,&ABrickflowStage::CaptureFilmPixels);}
        ApplySourceFrame(SourceFrame);SourceSettle=1;
    }
    SourceWarmup+=DeltaSeconds;if(SourceWarmup<10)return;
    if(!FilmPending.IsEmpty()){
        if(FilmSocket?!bFilmFrameCaptured:IFileManager::Get().FileSize(*FilmPending)<=100)return;
        FilmPending.Empty();bFilmFrameCaptured=false;++SourceFrame;SourceSettle=0;
    }
    if(SourceFrame>=SourceEnd){
        if(FilmSocket){FilmSocket->Close();UGameViewportClient::OnScreenshotCaptured().Remove(FilmScreenshotDelegate);ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(FilmSocket);FilmSocket=nullptr;}
        FFileHelper::SaveStringToFile(TEXT("complete\n"),*(SourceOutput/TEXT("complete.status")));FPlatformMisc::RequestExit(false);return;
    }
    if(!SourceSettle)ApplySourceFrame(SourceFrame);
    int32 Settle=6;FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmSettle="),Settle);
    if(++SourceSettle>=FMath::Max(2,Settle)){
        FilmPending=SourceOutput/FString::Printf(TEXT("frame-%06d.png"),SourceFrame);FScreenshotRequest::RequestScreenshot(FilmPending,false,false);
    }
}
