#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Core/Simulation.h"
#include "BrickflowStage.generated.h"

class UInstancedStaticMeshComponent;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UStaticMesh;
class UCameraComponent;
class FJsonObject;

UCLASS()
class BRICKFLOW_API ABrickflowStage : public AActor
{
    GENERATED_BODY()
public:
    ABrickflowStage();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void CalcCamera(float DeltaTime,FMinimalViewInfo& OutResult) override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;
    void SelectChapter(int32 Index);
    void TogglePlayback();
    void CycleSpeed();
    void SeekNormalized(float Position);
    void QueueRecipe(const FString& Recipe);
    void RestartBatch();
    void ToggleEvidence();
    FString Metric(int32 Index) const;
    FString ClockText() const;
    FString StatusText() const;
    FString SpeedText() const;
    FString EvidenceText() const;
    float Progress() const;
    bool IsPlaying() const { return bPlaying; }
    bool IsBusy() const { return bBusy; }
    bool IsEvidenceOpen() const { return bEvidence; }
    int32 ActiveChapter() const { return Chapter; }
private:
    struct FPart {
        FString Type,Record;
        FTransform Local,Base,JawBase,Last;
        int32 Sign=0,Lane=0,Station=0,RecordIndex=INDEX_NONE,Instance=0;
        UInstancedStaticMeshComponent* Component=nullptr;
    };
    TArray<FPart> Parts;
    TArray<TPair<double,double>> Centering[6][3];
    TMap<FString,TSharedPtr<FJsonObject>> Geometry;
    TMap<FString,TSharedPtr<FJsonObject>> MaterialData;
    TMap<FString,UInstancedStaticMeshComponent*> InstanceGroups;
    TMap<FString,UStaticMesh*> MeshCache;
    TMap<FString,UMaterialInstanceDynamic*> MaterialCache;
    TSharedPtr<FJsonObject> Asset;
    struct FFilmShot {
        FString Name,View;
        int32 First=0,Count=0,Subject=-1;
        double Start=0;
        bool Freeze=false;
    };
    TArray<FFilmShot> FilmShots;
    FString FilmDirectory,FilmPending;
    int32 FilmFrame=0,FilmLast=-1,FilmSettle=0,FilmExtraSettle=0,FilmStride=1,FilmAccepted=-1,FilmRejected=-1;
    double FilmWarmup=0;
    bool bFilmReady=false;
    class FSocket* FilmSocket=nullptr;
    FDelegateHandle FilmScreenshotDelegate;
    bool bFilmFrameCaptured=false;
    void CaptureFilmPixels(int32 Width,int32 Height,const TArray<FColor>& Pixels);
    void BuildFilmPlan();
    void TickFilm(float DeltaSeconds);
    void ApplyFilmFrame(int32 Frame);
    std::shared_ptr<brickflow::Simulation> Model;
    std::vector<brickflow::Request> RecipeRequests;
    FString Failure;
    FString CapturePath;
    FString MovieDirectory,MoviePending;
    int32 MovieFrames=0,MovieFrame=0,MovieSettle=0;
    int32 ControlExercise=0;
    double MovieStart=0;
    float CaptureWarmup=0;
    bool bCaptureRequested=false,bExitAfterCapture=false;
    double Time=0;
    float Speed=1;
    int32 Chapter=0;
    bool bBusy=true,bPlaying=true,bEvidence=false;
    FVector CameraFrom,CameraTarget,CameraLookFrom,CameraLookTarget;
    float CameraBlend=1;
    UPROPERTY() TObjectPtr<USceneComponent> Root;
    UPROPERTY() TObjectPtr<UCameraComponent> Camera;
    UPROPERTY() TObjectPtr<UMaterialInterface> BaseMaterial;
    UPROPERTY() TArray<TObjectPtr<UStaticMesh>> GeneratedMeshes;
    UPROPERTY() TArray<TObjectPtr<UMaterialInstanceDynamic>> GeneratedMaterials;
    UPROPERTY() TArray<TObjectPtr<UInstancedStaticMeshComponent>> GeneratedComponents;
    void RunNative(double PreserveTime=0);
    void BuildScene();
    void UpdateScene(bool Force=false);
    void CreateLighting();
    void OrbitHorizontal(float Amount);
    void OrbitVertical(float Amount);
    void Zoom(float Amount);
    void AddPart(const TSharedPtr<FJsonObject>& Definition,const FString& OverrideRecord=TEXT(""));
    UStaticMesh* Mesh(const FString& ID,const TArray<FString>& Materials,const FLinearColor& Tint);
    UMaterialInstanceDynamic* Material(const FString& ID,const FLinearColor& Tint);
    FTransform Driver(const FPart& Part) const;
};
