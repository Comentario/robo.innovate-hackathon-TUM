#include "BrickflowStage.h"
#include "Async/Async.h"
#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/InputComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Engine/GameViewportClient.h"
#include "GameFramework/PlayerController.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "HAL/FileManager.h"
#include "UnrealClient.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

ABrickflowStage::ABrickflowStage()
{
    PrimaryActorTick.bCanEverTick=true;
    bFindCameraComponentWhenViewTarget=true;
    Root=CreateDefaultSubobject<USceneComponent>(TEXT("FactoryRoot"));SetRootComponent(Root);
    Camera=CreateDefaultSubobject<UCameraComponent>(TEXT("PresentationCamera"));Camera->SetupAttachment(Root);
    Camera->SetFieldOfView(FMath::RadiansToDegrees(2*FMath::Atan(FMath::Tan(FMath::DegreesToRadians(43.f/2))*16.f/9)));
    Camera->bConstrainAspectRatio=true;Camera->AspectRatio=16.f/9;
}
void ABrickflowStage::BeginPlay()
{
    Super::BeginPlay();
    FString Json;
    if(!FFileHelper::LoadFileToString(Json,*(FPaths::ProjectContentDir()/TEXT("Data/factory.json")))||
        !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json),Asset)){
        Failure=TEXT("Factory geometry asset is missing or invalid");bBusy=false;return;
    }
    for(const auto& P:Asset->GetObjectField(TEXT("geometries"))->Values)Geometry.Add(FString(*P.Key),P.Value->AsObject());
    for(const auto& P:Asset->GetObjectField(TEXT("materials"))->Values)MaterialData.Add(FString(*P.Key),P.Value->AsObject());
    if(auto* PC=GetWorld()->GetFirstPlayerController()){
        PC->bAutoManageActiveCameraTarget=false;PC->SetViewTarget(this);Camera->SetActive(true);PC->bShowMouseCursor=false;EnableInput(PC);
        FInputModeGameAndUI Mode;Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);PC->SetInputMode(Mode);
        InputComponent->BindKey(EKeys::SpaceBar,IE_Pressed,this,&ABrickflowStage::TogglePlayback);
        InputComponent->BindKey(EKeys::E,IE_Pressed,this,&ABrickflowStage::ToggleEvidence);
        InputComponent->BindKey(EKeys::S,IE_Pressed,this,&ABrickflowStage::CycleSpeed);
        InputComponent->BindAxisKey(EKeys::MouseX,this,&ABrickflowStage::OrbitHorizontal);
        InputComponent->BindAxisKey(EKeys::MouseY,this,&ABrickflowStage::OrbitVertical);
        InputComponent->BindAxisKey(EKeys::MouseWheelAxis,this,&ABrickflowStage::Zoom);
        const FKey Keys[]={EKeys::One,EKeys::Two,EKeys::Three,EKeys::Four,EKeys::Five,EKeys::Six};
        for(int32 I=0;I<6;++I){FInputKeyBinding Binding(FInputChord(Keys[I]),IE_Pressed);
            Binding.KeyDelegate.GetDelegateForManualSet().BindLambda([this,I]{SelectChapter(I);});InputComponent->KeyBindings.Add(Binding);}
    }
    FString InitialMode;int32 InitialChapter=0;double InitialTime=0;
    if(FParse::Value(FCommandLine::Get(),TEXT("BrickflowMode="),InitialMode)&&InitialMode!=TEXT("mixed"))RecipeRequests.push_back({0,TCHAR_TO_UTF8(*InitialMode)});
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowChapter="),InitialChapter);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowTime="),InitialTime);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowCapture="),CapturePath);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowMovie="),MovieDirectory);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowMovieFrames="),MovieFrames);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilm="),FilmDirectory);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmStride="),FilmStride);
    FilmStride=FMath::Max(1,FilmStride);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmFirst="),FilmFrame);
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmLast="),FilmLast);
    if(!FilmDirectory.IsEmpty()){bPlaying=false;IFileManager::Get().MakeDirectory(*FilmDirectory,true);}
    MovieStart=InitialTime;
    if(!MovieDirectory.IsEmpty()){
        MovieFrames=FMath::Clamp(MovieFrames,24,2400);
        IFileManager::Get().MakeDirectory(*MovieDirectory,true);
        CapturePath=MovieDirectory/TEXT("reference.png");
    }
    bExitAfterCapture=FParse::Param(FCommandLine::Get(),TEXT("BrickflowExit"));
    if(!CapturePath.IsEmpty())bPlaying=false;
    CreateLighting();SelectChapter(InitialChapter);CameraBlend=1;
    Camera->SetWorldLocation(CameraTarget);Camera->SetWorldRotation((CameraLookTarget-CameraTarget).Rotation());
    RunNative(InitialTime);
}
void ABrickflowStage::RunNative(double PreserveTime)
{
    if(bBusy&&Model)return;
    bBusy=true;Failure.Empty();const bool Resume=bPlaying;bPlaying=false;
    const auto Requests=RecipeRequests;TWeakObjectPtr<ABrickflowStage> Weak(this);
    Async(EAsyncExecution::ThreadPool,[Weak,Requests,PreserveTime,Resume]{
        try{
            auto Result=std::make_shared<brickflow::Simulation>(Requests);Result->run();
            AsyncTask(ENamedThreads::GameThread,[Weak,Result,PreserveTime,Resume]{
                if(!Weak.IsValid())return;auto* Stage=Weak.Get();Stage->Model=Result;
                Stage->Time=FMath::Clamp(PreserveTime,0.,Result->total);Stage->BuildScene();
                Stage->UpdateScene(true);Stage->bBusy=false;Stage->bPlaying=Resume;
                UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_NATIVE_RESULT inspected=%d rejected=%d formed=%d pallets=%d seconds=%.12f bph=%.12f"),
                    Result->inspected,Result->rejected,Result->formed,Result->delivered,Result->total,Result->bricksPerHour);
            });
        }catch(const std::exception& Error){
            FString Message=UTF8_TO_TCHAR(Error.what());AsyncTask(ENamedThreads::GameThread,[Weak,Message]{
                if(Weak.IsValid()){Weak->Failure=Message;Weak->bBusy=false;}
            });
        }
    });
}
void ABrickflowStage::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if(Model&&!bBusy&&FParse::Param(FCommandLine::Get(),TEXT("BrickflowExerciseControls"))){
        if(ControlExercise==0){
            TogglePlayback();TogglePlayback();for(int32 I=0;I<5;++I)CycleSpeed();
            SelectChapter(3);SeekNormalized(.4f);++ControlExercise;QueueRecipe(TEXT("single"));
        }else if(ControlExercise==1){++ControlExercise;RestartBatch();}
        else if(ControlExercise==2){SeekNormalized(.4f);++ControlExercise;}
    }
    if(auto* PC=GetWorld()->GetFirstPlayerController())if(PC->GetViewTarget()!=this){PC->bAutoManageActiveCameraTarget=false;PC->SetViewTarget(this);}
    if(Model&&!bBusy){if(bPlaying){Time=FMath::Min(Model->total,Time+FMath::Min(DeltaSeconds,.1f)*Speed);if(Time>=Model->total)bPlaying=false;}UpdateScene();}
    if(CameraBlend<1){CameraBlend=FMath::Min(1.f,CameraBlend+DeltaSeconds/.95f);float U=CameraBlend*CameraBlend*(3-2*CameraBlend);
        FVector P=FMath::Lerp(CameraFrom,CameraTarget,U),Look=FMath::Lerp(CameraLookFrom,CameraLookTarget,U);
        Camera->SetWorldLocation(P);Camera->SetWorldRotation((Look-P).Rotation());}
    if(Model&&!bBusy&&!CapturePath.IsEmpty()){
        CaptureWarmup+=DeltaSeconds;
        if(!bCaptureRequested&&CaptureWarmup>=20){
            FScreenshotRequest::RequestScreenshot(CapturePath,!FParse::Param(FCommandLine::Get(),TEXT("BrickflowSceneOnly")),false);bCaptureRequested=true;
            auto Evidence=MakeShared<FJsonObject>();Evidence->SetStringField(TEXT("simulationBackend"),TEXT("native-cpp20"));
            Evidence->SetStringField(TEXT("referenceSha256"),Asset->GetStringField(TEXT("referenceSha256")));
            if(FParse::Param(FCommandLine::Get(),TEXT("BrickflowExerciseControls")))Evidence->SetBoolField(TEXT("controlExerciseComplete"),ControlExercise==3);
            Evidence->SetNumberField(TEXT("batchSeconds"),Model->total);Evidence->SetNumberField(TEXT("bricksPerHour"),Model->bricksPerHour);
            Evidence->SetNumberField(TEXT("palletsPerHour"),Model->palletsPerHour);Evidence->SetNumberField(TEXT("inspected"),Model->inspected);
            Evidence->SetNumberField(TEXT("rejected"),Model->rejected);Evidence->SetNumberField(TEXT("formed"),Model->formed);
            Evidence->SetNumberField(TEXT("delivered"),Model->delivered);Evidence->SetNumberField(TEXT("replayTime"),Time);
            Evidence->SetStringField(TEXT("cameraComponentLocation"),Camera->GetComponentLocation().ToString());
            Evidence->SetStringField(TEXT("cameraComponentRotation"),Camera->GetComponentRotation().ToString());
            Evidence->SetNumberField(TEXT("instanceGroups"),GeneratedComponents.Num());Evidence->SetNumberField(TEXT("dynamicParts"),Parts.Num());
            if(auto* PC=GetWorld()->GetFirstPlayerController()){
                Evidence->SetStringField(TEXT("activeViewTarget"),GetNameSafe(PC->GetViewTarget()));
                if(PC->PlayerCameraManager)Evidence->SetStringField(TEXT("activeCameraLocation"),PC->PlayerCameraManager->GetCameraLocation().ToString());
            }
            Evidence->SetStringField(TEXT("initialMode"),RecipeRequests.empty()?TEXT("mixed"):UTF8_TO_TCHAR(RecipeRequests.front().mode.c_str()));
            TArray<TSharedPtr<FJsonValue>> Pallets;
            for(const auto& Pallet:Model->pallets){
                auto Item=MakeShared<FJsonObject>();Item->SetNumberField(TEXT("t"),Pallet.time);
                Item->SetNumberField(TEXT("lane"),Pallet.lane);Item->SetNumberField(TEXT("cart"),Pallet.cart);
                Item->SetNumberField(TEXT("slot"),Pallet.slot);Item->SetNumberField(TEXT("shade"),Pallet.shade);
                TArray<TSharedPtr<FJsonValue>> Identities;
                for(int ID:Pallet.ids)Identities.Add(MakeShared<FJsonValueString>(UTF8_TO_TCHAR(Model->records[ID].id.c_str())));
                Item->SetArrayField(TEXT("ids"),Identities);Pallets.Add(MakeShared<FJsonValueObject>(Item));
            }
            Evidence->SetArrayField(TEXT("pallets"),Pallets);
            FString Encoded;FJsonSerializer::Serialize(Evidence,TJsonWriterFactory<>::Create(&Encoded));
            FFileHelper::SaveStringToFile(Encoded,*(CapturePath+TEXT(".evidence.json")));
            UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_NATIVE_CAPTURE requested %s"),*CapturePath);
        }
        if(bCaptureRequested&&CaptureWarmup>=22&&!MovieDirectory.IsEmpty()){
            if(!MoviePending.IsEmpty()){
                if(IFileManager::Get().FileSize(*MoviePending)<=100)return;
                MoviePending.Empty();++MovieFrame;MovieSettle=0;
            }
            if(MovieFrame>=MovieFrames){FPlatformMisc::RequestExit(false);return;}
            if(MovieSettle==0){
                Time=FMath::Min(Model->total,MovieStart+MovieFrame);UpdateScene(true);
                const int32 NextChapter=FMath::Min(5,MovieFrame*6/MovieFrames);
                if(Chapter!=NextChapter)SelectChapter(NextChapter);
            }
            if(++MovieSettle>=3){
                MoviePending=MovieDirectory/FString::Printf(TEXT("frame-%05d.png"),MovieFrame);
                FScreenshotRequest::RequestScreenshot(MoviePending,true,false);
            }
        }
        if(bCaptureRequested&&CaptureWarmup>=22&&MovieDirectory.IsEmpty()&&bExitAfterCapture&&IFileManager::Get().FileSize(*CapturePath)>100)FPlatformMisc::RequestExit(false);
    }
    if(Model&&!bBusy&&!FilmDirectory.IsEmpty())TickFilm(DeltaSeconds);
}
void ABrickflowStage::CalcCamera(float DeltaTime,FMinimalViewInfo& OutResult)
{
    Camera->GetCameraView(DeltaTime,OutResult);
}
void ABrickflowStage::EndPlay(const EEndPlayReason::Type Reason)
{
    Super::EndPlay(Reason);
}
void ABrickflowStage::SelectChapter(int32 Index)
{
    Chapter=FMath::Clamp(Index,0,5);
    const double P[][6]={{35,-9,0,125,.82,.8},{26.8,1,-13,10,.8,.75},{38.5,1,-13,15,.9,.8},
        {44.8,1,-13,13,1.,.85},{59,1,0,40,.9,.78},{35,-9,0,125,.82,.8}};
    const auto& V=P[Chapter];CameraFrom=Camera->GetComponentLocation();CameraLookFrom=CameraLookTarget;
    CameraLookTarget=FVector(V[0]*100,V[2]*100,V[1]*100);
    CameraTarget=CameraLookTarget+FVector(V[3]*FMath::Cos(V[5])*FMath::Cos(V[4])*100,
        V[3]*FMath::Cos(V[5])*FMath::Sin(V[4])*100,V[3]*FMath::Sin(V[5])*100);
    CameraBlend=0;bEvidence=Chapter==5;
}
void ABrickflowStage::OrbitHorizontal(float Amount)
{
    auto* PC=GetWorld()->GetFirstPlayerController();if(!PC||!PC->IsInputKeyDown(EKeys::RightMouseButton)||FMath::IsNearlyZero(Amount))return;
    FVector Offset=Camera->GetComponentLocation()-CameraLookTarget;Offset=Offset.RotateAngleAxis(Amount*.3f,FVector::UpVector);
    CameraBlend=1;CameraTarget=CameraLookTarget+Offset;Camera->SetWorldLocation(CameraTarget);Camera->SetWorldRotation((-Offset).Rotation());
}
void ABrickflowStage::OrbitVertical(float Amount)
{
    auto* PC=GetWorld()->GetFirstPlayerController();if(!PC||!PC->IsInputKeyDown(EKeys::RightMouseButton)||FMath::IsNearlyZero(Amount))return;
    FVector Offset=Camera->GetComponentLocation()-CameraLookTarget;FRotator Rotation=Offset.Rotation();Rotation.Pitch=FMath::Clamp(Rotation.Pitch+Amount*.3f,8.f,85.f);
    Offset=Rotation.Vector()*Offset.Length();CameraBlend=1;CameraTarget=CameraLookTarget+Offset;Camera->SetWorldLocation(CameraTarget);Camera->SetWorldRotation((-Offset).Rotation());
}
void ABrickflowStage::Zoom(float Amount)
{
    if(FMath::IsNearlyZero(Amount))return;FVector Offset=Camera->GetComponentLocation()-CameraLookTarget;
    Offset=Offset.GetSafeNormal()*FMath::Clamp(Offset.Length()*FMath::Exp(-Amount*.12f),250.,24000.);
    CameraBlend=1;CameraTarget=CameraLookTarget+Offset;Camera->SetWorldLocation(CameraTarget);
}
void ABrickflowStage::TogglePlayback(){if(!bBusy&&Model)bPlaying=!bPlaying;}
void ABrickflowStage::CycleSpeed(){const float Speeds[]={1,4,12,30,60};for(int32 I=0;I<5;++I)if(Speed==Speeds[I]){Speed=Speeds[(I+1)%5];return;}}
void ABrickflowStage::SeekNormalized(float Position){if(Model&&!bBusy){Time=FMath::Clamp(double(Position),0.,1.)*Model->total;UpdateScene(true);}}
void ABrickflowStage::QueueRecipe(const FString& Recipe){if(bBusy||!Model)return;RecipeRequests.push_back({Time,TCHAR_TO_UTF8(*Recipe)});RunNative(Time);}
void ABrickflowStage::RestartBatch(){
    if(bBusy||!Model)return;std::string Mode=RecipeRequests.empty()?"mixed":RecipeRequests.back().mode;
    RecipeRequests.clear();if(Mode!="mixed")RecipeRequests.push_back({0,Mode});RunNative(0);
}
void ABrickflowStage::ToggleEvidence(){bEvidence=!bEvidence;}
float ABrickflowStage::Progress() const{return Model?float(Time/Model->total):0;}
FString ABrickflowStage::Metric(int32 Index) const
{
    if(!Model)return TEXT("—");auto M=Model->metrics(Time);
    switch(Index){
    case 0:return FText::AsNumber(FMath::RoundToInt(Model->bricksPerHour)).ToString();
    case 1:return FString::Printf(TEXT("%.2f"),Model->palletsPerHour);
    case 2:return FText::AsNumber(M.inspected).ToString();
    default:return FText::AsNumber(M.delivered).ToString();}
}
FString ABrickflowStage::ClockText() const
{
    auto Clock=[](double Seconds){int32 S=int32(Seconds);return FString::Printf(TEXT("%02d:%02d:%02d"),S/3600,S/60%60,S%60);};
    return Clock(Time)+TEXT(" / ")+(Model?Clock(Model->total):TEXT("—"));
}
FString ABrickflowStage::StatusText() const
{
    if(!Failure.IsEmpty())return Failure;
    if(bBusy)return TEXT("Preparing the native production model…");
    if(Model&&!Model->completeInput)return TEXT("FLOW HELD AT FINITE STORAGE · SYNTHETIC INPUT");
    return TEXT("SIMULATED PRODUCTION · SYNTHETIC INPUT");
}
FString ABrickflowStage::SpeedText() const{return FString::Printf(TEXT("%.0f×"),Speed);}
FString ABrickflowStage::EvidenceText() const
{
    if(!Model)return TEXT("The native model is being prepared. No production results are available yet.");
    auto Current=Model->metrics(Time);int32 Warm=0,Copper=0,Russet=0;
    for(const auto& Bank:Current.banks){Warm+=Bank[0];Copper+=Bank[1];Russet+=Bank[2];}
    return FString::Printf(TEXT("MODELED BATCH RESULT\n\n%d complete pallets × 560 bricks / %.3f seconds × 3,600\n= %.3f conforming shipped bricks/h\n\n%.3f complete pallets/h\n%d inspected · %d rejected\n%d bricks in formed layers\n%d conforming shipped bricks\n\nCURRENT REPLAY STATE\n\n%d inspected · %d rejected\n%d bricks in formed layers\n%d complete pallets delivered\n%d / 20 source-layer cycles\nReserves: %d Warm · %d Copper · %d Russet\n\nHourly equivalent of a finite synthetic batch, including start-up and drain. Partial pallets remain inventory.\n\nKinematic simulation; no independent physical or industrial validation.\n\nReference: greenfield_30 · 7573180b519dfa27"),
        Model->delivered,Model->total,Model->bricksPerHour,Model->palletsPerHour,Model->inspected,Model->rejected,Model->formed,Model->delivered*560,
        Current.inspected,Current.rejected,Current.formed,Current.delivered,Current.cycles,Warm,Copper,Russet);
}
