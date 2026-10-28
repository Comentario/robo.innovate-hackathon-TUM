#include "BrickflowStage.h"
#include "FilmTiming.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include <stdexcept>

namespace {
FTransform EnclosureTransform(const TSharedPtr<FJsonObject>& O){
    const auto& P=O->GetArrayField(TEXT("position"));const auto& S=O->GetArrayField(TEXT("scale"));const auto& Q=O->GetArrayField(TEXT("rotation"));
    return FTransform(FQuat(-Q[0]->AsNumber(),-Q[2]->AsNumber(),-Q[1]->AsNumber(),Q[3]->AsNumber()),FVector(P[0]->AsNumber(),P[2]->AsNumber(),P[1]->AsNumber())*100,FVector(S[0]->AsNumber(),S[2]->AsNumber(),S[1]->AsNumber()));
}
double Attention(double X,double Minimum,double Maximum,double Margin){
    return brickflow::film::blend((X-Minimum+Margin)/Margin)*brickflow::film::blend((Maximum+Margin-X)/Margin);
}
}

void ABrickflowStage::BuildSourceEnclosures()
{
    const FString Path=ReviewRoot/TEXT("enclosures.json");FString Text;TSharedPtr<FJsonObject> Data;
    if(!FPaths::FileExists(Path)){UE_LOG(LogTemp,Warning,TEXT("No source service enclosure supplement; legacy cutaway geometry"));return;}
    if(!FFileHelper::LoadFileToString(Text,*Path)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Data))throw std::runtime_error("Invalid source enclosure supplement");
    if(Data->GetStringField(TEXT("referenceSha256"))!=SourceTour->GetStringField(TEXT("referenceSha256")))throw std::runtime_error("Enclosures and source reference differ");
    for(const auto& E:Data->GetObjectField(TEXT("geometries"))->Values)Geometry.Add(FString(*E.Key),E.Value->AsObject());
    for(const auto& E:Data->GetObjectField(TEXT("materials"))->Values)MaterialData.Add(FString(*E.Key),E.Value->AsObject());
    auto* Fade=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/M_FactoryEnclosureFade.M_FactoryEnclosureFade"));
    checkf(Fade,TEXT("Source enclosure fade material is required"));
    TMap<FString,UInstancedStaticMeshComponent*> Components;TMap<FString,int32> Groups;
    for(const auto& V:Data->GetArrayField(TEXT("instances"))){
        const auto D=V->AsObject(),E=D->GetObjectField(TEXT("serviceEnclosure"));const FString System=E->GetStringField(TEXT("system"));const int32 Lane=E->GetIntegerField(TEXT("lane"));
        checkf((System==TEXT("inspection")||System==TEXT("routing"))&&Lane>=0&&Lane<6,TEXT("Unknown source enclosure"));
        const FString GroupKey=System+FString::FromInt(Lane);
        if(!Groups.Contains(GroupKey)){FSourceEnclosure Group;Group.System=System;Group.Lane=Lane;Groups.Add(GroupKey,SourceEnclosures.Add(Group));}
        auto& Group=SourceEnclosures[Groups[GroupKey]];
        TArray<FString> Materials;for(const auto& M:D->GetArrayField(TEXT("materials")))Materials.Add(M->AsString());
        FLinearColor Tint=FLinearColor::White;if(D->HasField(TEXT("color"))){const auto& C=D->GetArrayField(TEXT("color"));Tint=FLinearColor(C[0]->AsNumber(),C[1]->AsNumber(),C[2]->AsNumber(),1);}
        const FString GeometryID=D->GetStringField(TEXT("geometry")),Key=GroupKey+GeometryID+FString::Join(Materials,TEXT("|"))+Tint.ToString();
        auto* C=Components.FindRef(Key);
        if(!C){C=NewObject<UInstancedStaticMeshComponent>(this);C->SetupAttachment(Root);C->SetStaticMesh(Mesh(GeometryID,Materials,Tint));
            for(int32 I=0;I<Materials.Num();++I){auto* MID=UMaterialInstanceDynamic::Create(Fade,this);MID->CopyMaterialUniformParameters(Material(Materials[I],Tint));MID->SetScalarParameterValue(TEXT("Coverage"),1);
                C->SetMaterial(I,MID);Group.Materials.Add(MID);GeneratedMaterials.Add(MID);}
            C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetCanEverAffectNavigation(false);C->SetMobility(EComponentMobility::Movable);C->RegisterComponent();GeneratedComponents.Add(C);Components.Add(Key,C);}
        C->AddInstance(EnclosureTransform(D->GetObjectField(TEXT("transform"))),true);
    }
    checkf(SourceEnclosures.Num()==12,TEXT("Expected all six inspection and routing enclosures"));
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_SOURCE_ENCLOSURES groups=%d meshes=%d source_geometry=true defaultCoverage=1 minimumCoverage=.28"),SourceEnclosures.Num(),Data->GetArrayField(TEXT("instances")).Num());
}

void ABrickflowStage::UpdateSourceEnclosures(double V)
{
    const bool ForceClosed=FParse::Param(FCommandLine::Get(),TEXT("BrickflowEnclosuresClosed"));
    // Evaluate attention over a fixed video-time window, never accumulated state.
    // Starting capture in the middle of a chunk therefore produces the same fade.
    TArray<FSourceCamera> Cameras;TArray<double> Weights;double Total=0;
    for(int32 I=-6;I<=6;++I){Cameras.Add(SourceCameraAt(FMath::Clamp(V+I*.18,0.,double(SourceTotalFrames-1)/30)));
        const double W=FMath::Exp(-I*I/12.);Weights.Add(W);Total+=W;}
    const auto& Lanes=SourceTour->GetArrayField(TEXT("laneZ"));
    auto Coverage=[&](const FString& System,int32 Lane){if(ForceClosed)return 1.;double Reveal=0;
        for(int32 I=0;I<Cameras.Num();++I){const auto& C=Cameras[I];const double X=C.Look.X/100,Z=C.Look.Y/100,Distance=(C.P-C.Look).Length()/100;
            const double Near=1-brickflow::film::blend((Distance-9)/8),LaneZ=Lanes[Lane]->AsNumber();
            const bool Inspection=System==TEXT("inspection");
            const double InX=Inspection?Attention(X,25.7,28.3,.65):Attention(X,28.65,46.9,1.0);
            const double InZ=Attention(Z,LaneZ-(Inspection?.65:1.85),LaneZ+(Inspection?.65:1.85),Inspection?.40:.12);
            Reveal+=Weights[I]*Near*InX*InZ;
        }
        return FMath::Clamp(1-.72*Reveal/Total,.28,1.);
    };
    SourceInspectionCoverage=SourceRoutingCoverage=1;
    for(int32 Lane=0;Lane<Lanes.Num();++Lane){SourceInspectionCoverage=FMath::Min(SourceInspectionCoverage,Coverage(TEXT("inspection"),Lane));SourceRoutingCoverage=FMath::Min(SourceRoutingCoverage,Coverage(TEXT("routing"),Lane));}
    for(auto& Group:SourceEnclosures){const double Alpha=Coverage(Group.System,Group.Lane);for(auto* Material:Group.Materials)Material->SetScalarParameterValue(TEXT("Coverage"),Alpha);}
}
