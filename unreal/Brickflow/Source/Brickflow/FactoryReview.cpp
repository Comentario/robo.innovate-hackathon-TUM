#include "BrickflowStage.h"
#include "Camera/CameraComponent.h"
#include "Components/InputComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/RectLightComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/RectLight.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "Misc/Base64.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UnrealClient.h"

namespace {
TSharedPtr<FJsonObject> ReadReviewJson(const FString& Path)
{
    FString Text;TSharedPtr<FJsonObject> Object;
    if(!FFileHelper::LoadFileToString(Text,*Path)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Object))
        return nullptr;
    return Object;
}
FTransform ReviewMatrix(const float* A)
{
    // Three column-vector matrix becomes UE's row-vector matrix before Y/Z reflection.
    const FMatrix M(FPlane(A[0],A[1],A[2],A[3]),FPlane(A[4],A[5],A[6],A[7]),
        FPlane(A[8],A[9],A[10],A[11]),FPlane(A[12],A[13],A[14],A[15]));
    const FTransform Source(M);const FVector P=Source.GetTranslation(),S=Source.GetScale3D();const FQuat Q=Source.GetRotation();
    return FTransform(FQuat(-Q.X,-Q.Z,-Q.Y,Q.W),FVector(P.X,P.Z,P.Y)*100,FVector(S.X,S.Z,S.Y));
}
FVector ReviewVector(const TArray<TSharedPtr<FJsonValue>>& Values)
{
    return FVector(Values[0]->AsNumber(),Values[1]->AsNumber(),Values[2]->AsNumber());
}
}

void ABrickflowStage::BeginReview(const FString& ManifestPath)
{
    bReviewMode=true;bBusy=false;bPlaying=false;
    // All nearest-LOD cassettes are retained for this inspection. Additional area
    // lights need a larger VSM culling allocation than the engine's default.
    if(auto* Limit=IConsoleManager::Get().FindConsoleVariable(TEXT("r.Shadow.Virtual.NonNanite.MaxCulledInstanceAllocationSize")))
        if(Limit->GetInt()<536870912)Limit->Set(536870912,ECVF_SetByCode);
    ReviewManifest=ReadReviewJson(ManifestPath);ReviewRoot=FPaths::GetPath(ManifestPath);
    checkf(ReviewManifest&&ReviewManifest->GetStringField(TEXT("schema"))==TEXT("brickflow.unreal-lighting-scene.v1"),TEXT("Invalid lighting review manifest"));
    checkf(ReviewManifest->GetBoolField(TEXT("snapshotOnly"))&&!ReviewManifest->GetBoolField(TEXT("nativeSimulationPorted")),TEXT("Review assets must be labeled as source snapshots"));
    Asset=ReadReviewJson(ReviewRoot/ReviewManifest->GetStringField(TEXT("geometry")));
    checkf(Asset&&Asset->GetBoolField(TEXT("snapshotOnly")),TEXT("Review geometry is missing or is not a snapshot"));
    for(const auto& P:Asset->GetObjectField(TEXT("geometries"))->Values)Geometry.Add(FString(*P.Key),P.Value->AsObject());
    for(const auto& P:Asset->GetObjectField(TEXT("materials"))->Values)MaterialData.Add(FString(*P.Key),P.Value->AsObject());
    // Exported ordinary parts already contain world poses, with no runtime bindings.
    for(const auto& V:Asset->GetArrayField(TEXT("instances"))){
        auto Definition=V->AsObject();checkf(!Definition->HasField(TEXT("binding")),TEXT("Review requires resolved world-space geometry"));
        AddPart(Definition);++ReviewInstanceCount;
    }
    struct FBatch {FString GeometryID;TArray<FString> Materials;FLinearColor Tint;TArray<FTransform> Transforms;};
    TMap<FString,FBatch> Batches;
    int32 BatchIndex=0;
    for(const auto& V:Asset->GetArrayField(TEXT("instanceBatches"))){
        auto Item=V->AsObject();checkf(!Item->HasField(TEXT("binding")),TEXT("Review instance binding must be resolved"));
        checkf(Item->GetStringField(TEXT("matrixEncoding"))==TEXT("base64-float32-little-endian-column-major"),TEXT("Unsupported review matrix encoding"));
        const int32 Count=Item->GetIntegerField(TEXT("count"));TArray<uint8> Bytes,Colors;
        const bool MatricesDecoded=FBase64::Decode(Item->GetStringField(TEXT("matrices")),Bytes);
        checkf(MatricesDecoded&&Bytes.Num()==int64(Count)*64,TEXT("Invalid packed review matrices"));
        FString ColorText;if(Item->TryGetStringField(TEXT("colors"),ColorText)){
            const bool ColorsDecoded=FBase64::Decode(ColorText,Colors);
            checkf(ColorsDecoded&&Colors.Num()==int64(Count)*12,TEXT("Invalid packed review colors"));
        }
        float ParentValues[16];const auto& Values=Item->GetArrayField(TEXT("parentMatrix"));check(Values.Num()==16);
        for(int32 J=0;J<16;++J)ParentValues[J]=Values[J]->AsNumber();const FTransform Parent=ReviewMatrix(ParentValues);
        TArray<FString> Materials;for(const auto& M:Item->GetArrayField(TEXT("materials")))Materials.Add(M->AsString());
        const FString GeometryID=Item->GetStringField(TEXT("geometry"));
        for(int32 I=0;I<Count;++I){
            FLinearColor Tint=FLinearColor::White;
            if(!Colors.IsEmpty()){float C[3];FMemory::Memcpy(C,Colors.GetData()+I*12,12);Tint=FLinearColor(C[0],C[1],C[2],1);}
            const FString Key=GeometryID+FString::Join(Materials,TEXT("|"))+Tint.ToString();auto& Batch=Batches.FindOrAdd(Key);
            if(Batch.Transforms.IsEmpty()){Batch.GeometryID=GeometryID;Batch.Materials=Materials;Batch.Tint=Tint;}
            float Matrix[16];FMemory::Memcpy(Matrix,Bytes.GetData()+I*64,64);const FTransform World=ReviewMatrix(Matrix)*Parent;
            Batch.Transforms.Add(World);++ReviewInstanceCount;
            if(I==0||I==Count-1){
                auto Sample=MakeShared<FJsonObject>();Sample->SetNumberField(TEXT("batch"),BatchIndex);Sample->SetNumberField(TEXT("instance"),I);
                TArray<TSharedPtr<FJsonValue>> Points;
                // Source origin and X/Y/Z one-metre basis, in reflected UE coordinates.
                for(const FVector& Basis:{FVector::ZeroVector,FVector(100,0,0),FVector(0,0,100),FVector(0,100,0)}){
                    const FVector P=World.TransformPosition(Basis);TArray<TSharedPtr<FJsonValue>> Coordinates;
                    for(double Number:{P.X,P.Y,P.Z})Coordinates.Add(MakeShared<FJsonValueNumber>(Number));
                    Points.Add(MakeShared<FJsonValueArray>(Coordinates));
                }
                Sample->SetArrayField(TEXT("unrealBasisPointsCm"),Points);ReviewMatrixSamples.Add(MakeShared<FJsonValueObject>(Sample));
            }
        }
        ++BatchIndex;
    }
    for(auto& Entry:Batches){
        auto& Batch=Entry.Value;auto* C=NewObject<UInstancedStaticMeshComponent>(this);C->SetupAttachment(Root);
        C->SetStaticMesh(Mesh(Batch.GeometryID,Batch.Materials,Batch.Tint));C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        C->SetCanEverAffectNavigation(false);C->SetMobility(EComponentMobility::Movable);C->RegisterComponent();
        C->AddInstances(Batch.Transforms,false,true,false);GeneratedComponents.Add(C);
    }
    for(const auto& V:ReviewManifest->GetArrayField(TEXT("cameras")))ReviewCameras.Add(V->AsObject());
    if(auto* PC=GetWorld()->GetFirstPlayerController()){
        PC->bAutoManageActiveCameraTarget=false;PC->SetViewTarget(this);Camera->SetActive(true);PC->bShowMouseCursor=false;EnableInput(PC);
        FInputModeGameOnly Mode;PC->SetInputMode(Mode);
        InputComponent->BindAxisKey(EKeys::MouseX,this,&ABrickflowStage::OrbitHorizontal);
        InputComponent->BindAxisKey(EKeys::MouseY,this,&ABrickflowStage::OrbitVertical);
        InputComponent->BindAxisKey(EKeys::MouseWheelAxis,this,&ABrickflowStage::Zoom);
        InputComponent->BindKey(EKeys::L,IE_Pressed,this,&ABrickflowStage::ToggleReviewLighting);
        const FKey Keys[]={EKeys::One,EKeys::Two,EKeys::Three,EKeys::Four,EKeys::Five,EKeys::Six,EKeys::Seven,EKeys::Eight,EKeys::Nine,EKeys::Zero};
        for(int32 I=0;I<FMath::Min(10,ReviewCameras.Num());++I){FInputKeyBinding Binding(FInputChord(Keys[I]),IE_Pressed);
            Binding.KeyDelegate.GetDelegateForManualSet().BindLambda([this,I]{SelectReviewCamera(I);});InputComponent->KeyBindings.Add(Binding);}
    }
    CreateLighting();BuildReviewLights();
    FString Name=ReviewManifest->GetStringField(TEXT("defaultCamera"));FParse::Value(FCommandLine::Get(),TEXT("BrickflowReviewCamera="),Name);
    int32 Index=0;for(int32 I=0;I<ReviewCameras.Num();++I)if(ReviewCameras[I]->GetStringField(TEXT("view"))==Name)Index=I;
    SelectReviewCamera(Index);CameraBlend=1;Camera->SetWorldLocation(CameraTarget);Camera->SetWorldRotation((CameraLookTarget-CameraTarget).Rotation());
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowCapture="),CapturePath);bExitAfterCapture=FParse::Param(FCommandLine::Get(),TEXT("BrickflowExit"));
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_REVIEW_READY source=%s state=%s time=%.6f instances=%d groups=%d nativeSimulationPorted=false snapshotOnly=true lighting=%s"),
        *ReviewManifest->GetStringField(TEXT("referenceSha256")),*ReviewManifest->GetStringField(TEXT("snapshotName")),ReviewManifest->GetNumberField(TEXT("snapshotTime")),ReviewInstanceCount,GeneratedComponents.Num(),*ReviewVariant);
}

void ABrickflowStage::SelectReviewCamera(int32 Index)
{
    if(!ReviewCameras.IsValidIndex(Index))return;Chapter=Index;const auto& V=ReviewCameras[Index];
    CameraFrom=Camera->GetComponentLocation();CameraLookFrom=CameraLookTarget;
    CameraTarget=ReviewVector(V->GetArrayField(TEXT("unrealPositionCm")));
    CameraLookTarget=V->HasField(TEXT("unrealTargetCm"))?ReviewVector(V->GetArrayField(TEXT("unrealTargetCm"))):
        CameraTarget+ReviewVector(V->GetArrayField(TEXT("unrealForward")))*1000;
    Camera->SetFieldOfView(V->GetNumberField(TEXT("unrealHorizontalFov")));CameraBlend=0;
}

void ABrickflowStage::BuildReviewLights()
{
    FString Path;ReviewVariant=TEXT("baseline");
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowReviewLighting="),ReviewVariant);
    if(!FParse::Value(FCommandLine::Get(),TEXT("BrickflowReviewRig="),Path))return;
    const auto Rig=ReadReviewJson(Path);checkf(Rig,TEXT("Review lighting rig is invalid"));
    for(const auto& V:Rig->GetArrayField(TEXT("lights"))){
        const auto L=V->AsObject();FVector P=ReviewVector(L->GetArrayField(TEXT("positionCm"))),Target=ReviewVector(L->GetArrayField(TEXT("targetCm")));
        auto* Light=GetWorld()->SpawnActor<ARectLight>(P,(Target-P).Rotation());Light->Tags.Add(FName(*L->GetStringField(TEXT("id"))));
        auto* C=Cast<URectLightComponent>(Light->GetLightComponent());C->SetMobility(EComponentMobility::Movable);
        C->SetIntensity(L->GetNumberField(TEXT("intensity")));C->SetSourceWidth(L->GetNumberField(TEXT("widthCm")));
        C->SetSourceHeight(L->GetNumberField(TEXT("heightCm")));C->SetAttenuationRadius(L->GetNumberField(TEXT("radiusCm")));
        C->SetCastShadows(L->GetBoolField(TEXT("castShadows")));C->SetVisibility(ReviewVariant==TEXT("candidate"));ReviewLights.Add(Light);
    }
    bReviewCandidate=ReviewVariant==TEXT("candidate");
}

void ABrickflowStage::ToggleReviewLighting()
{
    bReviewCandidate=!bReviewCandidate;ReviewVariant=bReviewCandidate?TEXT("candidate"):TEXT("baseline");
    for(auto& Actor:ReviewLights)if(auto* Light=Cast<ARectLight>(Actor.Get()))Light->GetLightComponent()->SetVisibility(bReviewCandidate);
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_REVIEW_LIGHTING %s"),*ReviewVariant);
}

void ABrickflowStage::TickReview(float DeltaSeconds)
{
    if(CameraBlend<1){CameraBlend=FMath::Min(1.f,CameraBlend+DeltaSeconds/.95f);const float U=CameraBlend*CameraBlend*(3-2*CameraBlend);
        const FVector P=FMath::Lerp(CameraFrom,CameraTarget,U),Look=FMath::Lerp(CameraLookFrom,CameraLookTarget,U);
        Camera->SetWorldLocation(P);Camera->SetWorldRotation((Look-P).Rotation());}
    if(CapturePath.IsEmpty())return;CaptureWarmup+=DeltaSeconds;
    if(!bCaptureRequested&&CaptureWarmup>=10){
        FScreenshotRequest::RequestScreenshot(CapturePath,false,false);bCaptureRequested=true;
        auto Evidence=MakeShared<FJsonObject>();Evidence->SetStringField(TEXT("renderBackend"),TEXT("Unreal Vulkan"));
        Evidence->SetBoolField(TEXT("snapshotOnly"),true);Evidence->SetBoolField(TEXT("nativeSimulationPorted"),false);
        Evidence->SetStringField(TEXT("referenceSha256"),ReviewManifest->GetStringField(TEXT("referenceSha256")));
        Evidence->SetStringField(TEXT("geometrySha256"),ReviewManifest->GetStringField(TEXT("geometrySha256")));
        Evidence->SetStringField(TEXT("state"),ReviewManifest->GetStringField(TEXT("snapshotName")));
        Evidence->SetNumberField(TEXT("snapshotTime"),ReviewManifest->GetNumberField(TEXT("snapshotTime")));
        Evidence->SetStringField(TEXT("camera"),ReviewCameras[Chapter]->GetStringField(TEXT("view")));
        Evidence->SetStringField(TEXT("cameraPosition"),Camera->GetComponentLocation().ToString());
        Evidence->SetStringField(TEXT("lightingVariant"),ReviewVariant);Evidence->SetNumberField(TEXT("candidateLights"),ReviewLights.Num());
        Evidence->SetNumberField(TEXT("meshInstances"),ReviewInstanceCount);Evidence->SetStringField(TEXT("validationStatus"),TEXT("unvalidated"));
        Evidence->SetArrayField(TEXT("matrixSamples"),ReviewMatrixSamples);
        FString Text;FJsonSerializer::Serialize(Evidence,TJsonWriterFactory<>::Create(&Text));FFileHelper::SaveStringToFile(Text,*(CapturePath+TEXT(".evidence.json")));
    }
    if(bCaptureRequested&&CaptureWarmup>=12&&bExitAfterCapture&&IFileManager::Get().FileSize(*CapturePath)>100)FPlatformMisc::RequestExit(false);
}
