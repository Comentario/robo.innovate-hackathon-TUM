#include "BrickflowStage.h"
#include "Camera/CameraComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace {
TSharedPtr<FJsonObject> ReadSourceJson(const FString& Path){FString Text;TSharedPtr<FJsonObject> O;
    if(!FFileHelper::LoadFileToString(Text,*Path)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),O))throw std::runtime_error("Missing source-replay JSON");return O;}
FTransform SourceTransform(const TSharedPtr<FJsonObject>& O){const auto& P=O->GetArrayField(TEXT("position"));const auto& S=O->GetArrayField(TEXT("scale"));const auto& Q=O->GetArrayField(TEXT("rotation"));
    return FTransform(FQuat(-Q[0]->AsNumber(),-Q[2]->AsNumber(),-Q[1]->AsNumber(),Q[3]->AsNumber()),FVector(P[0]->AsNumber(),P[2]->AsNumber(),P[1]->AsNumber())*100,FVector(S[0]->AsNumber(),S[2]->AsNumber(),S[1]->AsNumber()));}
FTransform SourcePose(const brickflow::replay::State& S){const auto& P=S.pose;const auto& N=S.normal;
    const FQuat Q=FQuat::FindBetweenNormals(FVector(0,1,0),FVector(N[0],N[1],N[2]))*FQuat(FVector(0,1,0),P[3]);
    return FTransform(FQuat(-Q.X,-Q.Z,-Q.Y,Q.W),FVector(P[0],P[2],P[1])*100,FVector(S.visible?1:0));}
bool Starts(const std::string& Value,const char* Prefix){return Value.starts_with(Prefix);}
}

void ABrickflowStage::BeginSourceReplay(const FString& ManifestPath)
{
    bSourceReplay=true;bSourceAudit=FParse::Param(FCommandLine::Get(),TEXT("BrickflowSourceAudit"));
    ReviewRoot=FPaths::GetPath(ManifestPath);auto Manifest=ReadSourceJson(ManifestPath);
    FString TourPath;if(!FParse::Value(FCommandLine::Get(),TEXT("BrickflowTour="),TourPath))throw std::runtime_error("A source tour plan is required");
    SourceTour=ReadSourceJson(TourPath);
    if(SourceTour->GetStringField(TEXT("referenceSha256"))!=Manifest->GetStringField(TEXT("referenceSha256")))throw std::runtime_error("Tour and source reference differ");
    SourceTimeline=std::make_shared<brickflow::replay::Replay>();SourceTimeline->load(TCHAR_TO_UTF8(*(ReviewRoot/TEXT("replay.bin"))));
    FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilm="),SourceOutput);if(SourceOutput.IsEmpty())throw std::runtime_error("Source film output is required");
    IFileManager::Get().MakeDirectory(*SourceOutput,true);FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmFirst="),SourceFrame);
    SourceTotalFrames=SourceTour->GetIntegerField(TEXT("frames"));SourceEnd=SourceTotalFrames;FParse::Value(FCommandLine::Get(),TEXT("BrickflowFilmLast="),SourceEnd);
    SourceEnd=FMath::Min(SourceEnd,SourceTotalFrames);bPlaying=false;bBusy=false;
    if(!bSourceAudit){BeginReview(ManifestPath);BuildSourceEnclosures();BuildSourceParts();}
    else bReviewMode=true;
    FString Encoded;FJsonSerializer::Serialize(SourceTour,TJsonWriterFactory<>::Create(&Encoded));FFileHelper::SaveStringToFile(Encoded,*(SourceOutput/TEXT("tour.json")));
    FFileHelper::SaveStringToFile(TEXT("frame,nativeSeconds,speed,subject,x,y,z,visible,cameraX,cameraY,cameraZ,lookX,lookY,lookZ,fov,view,inspectionCoverage,routingCoverage\n"),*(SourceOutput/TEXT("trace.csv")));
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_SOURCE_REPLAY_READY hash=%s records=%d tracks=%llu frames=%d independentNativePlanner=false"),
        *Manifest->GetStringField(TEXT("referenceSha256")),int(SourceTimeline->records.size()),static_cast<unsigned long long>(SourceTimeline->trackCount),SourceTotalFrames);
}

void ABrickflowStage::BuildSourceParts()
{
    auto Definitions=ReadSourceJson(ReviewRoot/TEXT("parts.json"));
    for(const auto& V:Definitions->GetArrayField(TEXT("parts"))){auto D=V->AsObject(),B=D->GetObjectField(TEXT("binding"));FPart Part;
        Part.Type=B->GetStringField(TEXT("type"));Part.Record=B->GetStringField(TEXT("record"));Part.RecordIndex=SourceTimeline->named(TCHAR_TO_UTF8(*Part.Record));
        Part.Base=SourceTransform(B->GetObjectField(TEXT("base")));Part.Local=SourceTransform(D->GetObjectField(TEXT("transform")));
        if(B->HasField(TEXT("parentTransform")))Part.JawBase=SourceTransform(B->GetObjectField(TEXT("parentTransform")));
        double Value;if(B->TryGetNumberField(TEXT("sign"),Value))Part.Sign=Value;
        const TSet<FString> Supported={TEXT("actor"),TEXT("mast"),TEXT("trolley"),TEXT("beam"),TEXT("sourceBeam"),TEXT("gripperJaw"),TEXT("palletJaw"),TEXT("forkSleeve"),TEXT("forkPost"),TEXT("forkTop")};
        checkf(Supported.Contains(Part.Type),TEXT("Unsupported source animation binding: %s"),*Part.Type);
        TArray<FString> Materials;for(const auto& M:D->GetArrayField(TEXT("materials")))Materials.Add(M->AsString());
        FLinearColor Tint=FLinearColor::White;if(D->HasField(TEXT("color"))){const auto& C=D->GetArrayField(TEXT("color"));Tint=FLinearColor(C[0]->AsNumber(),C[1]->AsNumber(),C[2]->AsNumber(),1);}
        const FString GeometryID=D->GetStringField(TEXT("geometry")),Key=GeometryID+FString::Join(Materials,TEXT("|"))+Tint.ToString();
        auto* C=SourceInstanceGroups.FindRef(Key);if(!C){C=NewObject<UInstancedStaticMeshComponent>(this);C->SetupAttachment(Root);C->SetStaticMesh(Mesh(GeometryID,Materials,Tint));
            C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetCanEverAffectNavigation(false);C->SetMobility(EComponentMobility::Movable);C->RegisterComponent();GeneratedComponents.Add(C);SourceInstanceGroups.Add(Key,C);}
        Part.Component=C;Part.Instance=C->AddInstance(Part.Local*Part.Base,true);SourceParts.Add(Part);
    }
    const auto Brick=Definitions->GetObjectField(TEXT("brick"));TArray<FString> Materials;for(const auto& M:Brick->GetArrayField(TEXT("materials")))Materials.Add(M->AsString());
    const uint32 Palette[]={0xc39a70,0xa56d4b,0x77503c,0xe0cba7,0x4d382e};
    for(int32 Color=0;Color<5;++Color){FSourceBrickGroup Group;
        for(int32 I=0;I<int32(SourceTimeline->records.size());++I){const auto& R=SourceTimeline->records[I];if(R.kind=="brick"&&(R.good?R.shade:R.extreme?3:4)==Color)Group.IDs.Add(I);}
        if(Group.IDs.IsEmpty())continue;const uint32 RGB=Palette[Color];const auto Tint=FLinearColor::FromSRGBColor(FColor((RGB>>16)&255,(RGB>>8)&255,RGB&255));
        auto* C=NewObject<UInstancedStaticMeshComponent>(this);C->SetupAttachment(Root);C->SetStaticMesh(Mesh(Brick->GetStringField(TEXT("geometry")),Materials,Tint));
        C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetCanEverAffectNavigation(false);C->SetMobility(EComponentMobility::Movable);C->RegisterComponent();GeneratedComponents.Add(C);
        Group.Component=C;Group.Transforms.Init(FTransform::Identity,Group.IDs.Num());C->AddInstances(Group.Transforms,false,true,false);SourceBrickGroups.Add(MoveTemp(Group));
    }
}

FTransform ABrickflowStage::SourceDriver(const FPart& Part) const
{
    const auto& R=SourceTimeline->records[Part.RecordIndex];const auto State=SourceTimeline->state(Part.RecordIndex,Time);const auto& P=State.pose;auto RootPose=SourcePose(State);
    if(Part.Type==TEXT("actor"))return RootPose;
    if(!State.visible){auto Out=Part.Base;Out.SetScale3D(FVector::ZeroVector);return Out;}
    const auto* Stroke=SourceTimeline->segment(Part.RecordIndex,Time);const auto& Kind=SourceTimeline->kind(Stroke);
    if(Part.Type==TEXT("gripperJaw")||Part.Type==TEXT("palletJaw")){
        double Z;
        if(Part.Type==TEXT("palletJaw")){double Closed=Stroke&&(Starts(Kind,"lift-supported-output")||Starts(Kind,"finished-pallet-bridge")||Starts(Kind,"lower-pallet-on"))?1:0;
            if(Kind=="lower-pallet-lifting-frame"&&Time>=Stroke->end)Closed=FMath::Min(1.,(Time-Stroke->end)/.3);
            if(Kind=="lower-pallet-on-transport-cart"&&Time>=Stroke->end)Closed=1-FMath::Min(1.,(Time-Stroke->end)/.2);Z=Part.Sign*(.70-.15*Closed);
        }else{bool Held=false;for(auto Prefix:{"lift-36","distribute-2x6","place-on","raise-six","side-pick-and","place-six","lift-complete","transfer-complete","place-guided"})Held|=Starts(Kind,Prefix);
            if(Stroke&&Starts(Kind,"place")&&Time>Stroke->end+.07)Held=false;Z=Part.Sign*(Held?.3575:.40);}
        auto Local=Part.JawBase;auto Position=Local.GetTranslation();Position.Y=Z*100;Local.SetTranslation(Position);return Local*RootPose;
    }
    if(Part.Type.StartsWith(TEXT("fork"))){const FString Vehicle=TEXT("amr-")+Part.Record.Right(1);const auto V=SourceTimeline->state(SourceTimeline->named(TCHAR_TO_UTF8(*Vehicle)),Time).pose;
        const double Reach=FMath::Max(0.,V[0]-1.4-P[0]),Level=FMath::Max(1.05,P[1]+.18)-P[1];auto Local=Part.JawBase;auto Position=Local.GetTranslation();auto Scale=Local.GetScale3D();
        if(Part.Type==TEXT("forkSleeve")){Position=FVector((1.20+Reach)*100,Part.Sign*30,Level*100);}
        else if(Part.Type==TEXT("forkPost")){const double Length=FMath::Max(.06,Level-.18);Position=FVector(65,Part.Sign*30,(.18+Length/2)*100);Scale.Z=Length;}
        else Position.Z=Level*100;
        Local.SetTranslation(Position);Local.SetScale3D(Scale);return Local*RootPose;
    }
    FTransform Out=Part.Base;
    if(Part.Type==TEXT("sourceBeam")||Part.Type==TEXT("beam")){auto Position=Out.GetTranslation();Position.X=P[0]*100;Out.SetTranslation(Position);return Out;}
    const double Top=R.kind=="rowHead"?3.25:R.kind=="rowPusher"?2.4:R.kind=="dispatch"?4.95:Starts(R.id,"stacker-")?3.58:4.08;
    if(Part.Type==TEXT("trolley")){Out.SetTranslation(FVector(P[0]*100,P[2]*100,(Top+.07)*100));return Out;}
    if(Part.Type==TEXT("mast")){
        double X=P[0],Y=0,Z=P[2],SX=.055,SY=0,SZ=.055;
        if(R.kind=="layerStop"){const double Bottom=P[1]-.05;SY=FMath::Max(.04,Bottom-(1.25-.27));Y=1.25-.27+SY/2;X+=.20;SX=SZ=.035;}
        else if(R.kind=="centeringJaw"){TArray<FString> A;Part.Record.ParseIntoArray(A,TEXT("-"));const int L=FCString::Atoi(*A[1]),S=FCString::Atoi(*A[2]),Side=Part.Record.EndsWith(TEXT("--1"))?-1:1;
            const double LaneZ=SourceTour->GetArrayField(TEXT("laneZ"))[L]->AsNumber(),Back=LaneZ+(S-1)*1.2+Side*.62;
            X=Side<0?52.6:53.4;Y=1.25+.08;Z=(P[2]+Back)/2;SX=SY=.035;SZ=FMath::Max(.04,FMath::Abs(P[2]-Back));
        }else if(R.kind=="guideGate"){const double Bottom=P[1]+.055;SY=FMath::Max(.02,2.34-Bottom);Y=Bottom+SY/2;Z-=.40;SX=SZ=.035;}
        else if(R.kind=="bankLift"){SY=FMath::Max(.06,P[1]-.30);Y=.15+SY/2;Z+=.19;SX=SZ=.035;}
        else if(R.kind=="rejectPusher"){const int L=FCString::Atoi(*Part.Record.RightChop(7));const double Back=SourceTour->GetArrayField(TEXT("laneZ"))[L]->AsNumber()-.53;
            SZ=FMath::Max(.05,P[2]-Back);Z=Back+SZ/2;Y=1.25+.035;SX=SY=.045;
        }else{const double Bottom=P[1]+(R.kind=="dispatch"?.38:R.kind=="rowPusher"?.37:.25);SY=FMath::Max(.03,Top-Bottom);Y=Bottom+SY/2;SX=SZ=R.kind=="dispatch"?.12:.055;}
        return FTransform(FQuat::Identity,FVector(X*100,Z*100,Y*100),FVector(SX,SZ,SY));
    }
    throw std::runtime_error("Unimplemented source binding");
}

void ABrickflowStage::UpdateSourceScene()
{
    TSet<UInstancedStaticMeshComponent*> Dirty;
    for(auto& Part:SourceParts){const FTransform Transform=Part.Local*SourceDriver(Part);Part.Component->UpdateInstanceTransform(Part.Instance,Transform,true,false,true);Dirty.Add(Part.Component);}
    for(auto* C:Dirty)C->MarkRenderStateDirty();
    for(auto& Group:SourceBrickGroups){for(int32 I=0;I<Group.IDs.Num();++I)Group.Transforms[I]=SourcePose(SourceTimeline->state(Group.IDs[I],Time));
        Group.Component->BatchUpdateInstancesTransforms(0,Group.Transforms,true,true,true);}
}
