#include "BrickflowStage.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/RectLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Engine/RectLight.h"
#include "Engine/SkyLight.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "ImageUtils.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "MeshDescription.h"
#include "StaticMeshAttributes.h"
#include "Dom/JsonObject.h"
#include "Misc/Paths.h"

namespace {
FVector ThreeVector(const TArray<TSharedPtr<FJsonValue>>& A,double Scale=1){return FVector(A[0]->AsNumber()*Scale,A[2]->AsNumber()*Scale,A[1]->AsNumber()*Scale);}
FTransform Transform(const TSharedPtr<FJsonObject>& Object){
    const auto& Q=Object->GetArrayField(TEXT("rotation"));
    FQuat Rotation(-Q[0]->AsNumber(),-Q[2]->AsNumber(),-Q[1]->AsNumber(),Q[3]->AsNumber());Rotation.Normalize();
    return FTransform(Rotation,ThreeVector(Object->GetArrayField(TEXT("position")),100),ThreeVector(Object->GetArrayField(TEXT("scale"))));
}
FLinearColor Color(const TArray<TSharedPtr<FJsonValue>>& A){return FLinearColor(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber(),1);}
bool Prefix(std::string_view Value,std::string_view Start){return Value.substr(0,Start.size())==Start;}
FTransform NativePose(const brickflow::Pose& P){return FTransform(FRotator(0,-FMath::RadiansToDegrees(P[3]),0),FVector(P[0]*100,P[2]*100,P[1]*100));}
}

UMaterialInstanceDynamic* ABrickflowStage::Material(const FString& ID,const FLinearColor& Tint)
{
    FString Key=ID+Tint.ToString();if(auto* Cached=MaterialCache.Find(Key))return *Cached;
    if(!BaseMaterial)BaseMaterial=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/M_FactorySurface.M_FactorySurface"));
    if(!BaseMaterial)BaseMaterial=LoadObject<UMaterialInterface>(nullptr,TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
    auto Source=MaterialData.FindChecked(ID);bool DoubleSided=false;
    Source->TryGetBoolField(TEXT("doubleSided"),DoubleSided);
    UMaterialInterface* Surface=BaseMaterial;
    if(DoubleSided)Surface=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/M_FactorySurfaceTwoSided.M_FactorySurfaceTwoSided"));
    checkf(Surface,TEXT("Required factory surface material is missing"));
    auto* MID=UMaterialInstanceDynamic::Create(Surface,this);
    FLinearColor Base=Color(Source->GetArrayField(TEXT("color")));
    float Roughness=.48f,Metallic=0;
    if(Base.Equals(FLinearColor(.5210,.5841,.5776,1),.002f)){Base=FLinearColor(.018,.027,.038,1);Roughness=.32f;}
    else if(Base.Equals(FLinearColor(.2664,.3278,.3419,1),.002f)){Metallic=.8f;Roughness=.29f;}
    else if(Base.G>Base.R*1.4f&&Base.G>Base.B){Metallic=.25f;Roughness=.36f;}
    if(Base.R>.99f&&Base.G>.99f&&Base.B>.99f&&!Tint.Equals(FLinearColor::White))Roughness=.83f;
    MID->SetVectorParameterValue(TEXT("BaseColor"),Base*Tint);
    MID->SetVectorParameterValue(TEXT("Color"),Base*Tint);
    MID->SetScalarParameterValue(TEXT("Roughness"),Roughness);
    MID->SetScalarParameterValue(TEXT("Metallic"),Metallic);
    FString Image;
    if(Source->TryGetStringField(TEXT("texture"),Image)){
        auto* Texture=FImageUtils::ImportFileAsTexture2D((bReviewMode?ReviewRoot:FPaths::ProjectContentDir()/TEXT("Data"))/Image);
        if(Texture)MID->SetTextureParameterValue(TEXT("BaseTexture"),Texture);
    }
    GeneratedMaterials.Add(MID);MaterialCache.Add(Key,MID);return MID;
}
UStaticMesh* ABrickflowStage::Mesh(const FString& ID,const TArray<FString>& Materials,const FLinearColor& Tint)
{
    FString Key=ID+FString::Join(Materials,TEXT("|"))+Tint.ToString();if(auto* Cached=MeshCache.Find(Key))return *Cached;
    const auto Source=Geometry.FindChecked(ID);
    const auto& Vertices=Source->GetArrayField(TEXT("positions"));const auto& Normals=Source->GetArrayField(TEXT("normals"));
    const auto& UV=Source->GetArrayField(TEXT("uv"));const auto& Indices=Source->GetArrayField(TEXT("indices"));
    FMeshDescription Description;FStaticMeshAttributes Attributes(Description);Attributes.Register();
    auto Positions=Attributes.GetVertexPositions();auto InstanceNormals=Attributes.GetVertexInstanceNormals();
    auto Tangents=Attributes.GetVertexInstanceTangents();auto Signs=Attributes.GetVertexInstanceBinormalSigns();
    auto UVs=Attributes.GetVertexInstanceUVs();UVs.SetNumChannels(1);
    auto SlotNames=Attributes.GetPolygonGroupMaterialSlotNames();
    TArray<FVertexID> VertexIDs;
    for(int32 I=0;I<Vertices.Num();I+=3){FVertexID V=Description.CreateVertex();VertexIDs.Add(V);
        Positions[V]=FVector3f(Vertices[I]->AsNumber()*100,Vertices[I+2]->AsNumber()*100,Vertices[I+1]->AsNumber()*100);}
    TArray<FPolygonGroupID> Groups;
    for(int32 I=0;I<Materials.Num();++I){auto G=Description.CreatePolygonGroup();Groups.Add(G);SlotNames[G]=FName(*FString::Printf(TEXT("Material%d"),I));}
    for(int32 I=0;I<Indices.Num();I+=3){
        int32 MaterialIndex=0;
        if(Materials.Num()>1)for(const auto& Entry:Source->GetArrayField(TEXT("groups"))){auto G=Entry->AsObject();
            if(I>=G->GetIntegerField(TEXT("start"))&&I<G->GetIntegerField(TEXT("start"))+G->GetIntegerField(TEXT("count")))MaterialIndex=G->GetIntegerField(TEXT("materialIndex"));}
        TArray<FVertexInstanceID> Corners;
        // Y/Z reflection also converts Three's CCW front faces to Unreal's CW faces.
        for(int32 Offset:{0,1,2}){
            int32 Index=int32(Indices[I+Offset]->AsNumber());auto VI=Description.CreateVertexInstance(VertexIDs[Index]);Corners.Add(VI);
            FVector3f N=Normals.Num()>Index*3+2?FVector3f(Normals[Index*3]->AsNumber(),Normals[Index*3+2]->AsNumber(),Normals[Index*3+1]->AsNumber()):FVector3f(0,0,1);
            InstanceNormals[VI]=N;FVector3f Axis=FMath::Abs(N.Z)>.9f?FVector3f(0,1,0):FVector3f(0,0,1);
            Tangents[VI]=FVector3f::CrossProduct(Axis,N).GetSafeNormal();Signs[VI]=1;
            UVs.Set(VI,0,UV.Num()>Index*2+1?FVector2f(UV[Index*2]->AsNumber(),1-UV[Index*2+1]->AsNumber()):FVector2f::ZeroVector);
        }
        Description.CreatePolygon(Groups[FMath::Clamp(MaterialIndex,0,Groups.Num()-1)],Corners);
    }
    auto* Result=NewObject<UStaticMesh>(this);
    for(int32 I=0;I<Materials.Num();++I)Result->GetStaticMaterials().Add(FStaticMaterial(Material(Materials[I],Tint),FName(*FString::Printf(TEXT("Material%d"),I))));
    UStaticMesh::FBuildMeshDescriptionsParams Options;Options.bFastBuild=true;Options.bBuildSimpleCollision=false;
    Options.bMarkPackageDirty=false;Options.bUseHashAsGuid=true;
    Result->BuildFromMeshDescriptions({&Description},Options);
    GeneratedMeshes.Add(Result);MeshCache.Add(Key,Result);return Result;
}
void ABrickflowStage::AddPart(const TSharedPtr<FJsonObject>& Definition,const FString& OverrideRecord)
{
    TArray<FString> Materials;for(const auto& V:Definition->GetArrayField(TEXT("materials")))Materials.Add(V->AsString());
    const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
    FLinearColor Tint=Definition->TryGetArrayField(TEXT("color"),Values)?Color(*Values):FLinearColor::White;
    FString GeometryID=Definition->GetStringField(TEXT("geometry"));FString Key=GeometryID+FString::Join(Materials,TEXT("|"))+Tint.ToString();
    UInstancedStaticMeshComponent* Component=nullptr;
    if(auto* Cached=InstanceGroups.Find(Key))Component=*Cached;
    else{
        Component=NewObject<UInstancedStaticMeshComponent>(this);Component->SetupAttachment(Root);
        Component->SetStaticMesh(Mesh(GeometryID,Materials,Tint));Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Component->SetCanEverAffectNavigation(false);Component->SetMobility(EComponentMobility::Movable);
        Component->RegisterComponent();GeneratedComponents.Add(Component);InstanceGroups.Add(Key,Component);
    }
    FPart Part;Part.Component=Component;Part.Local=Transform(Definition->GetObjectField(TEXT("transform")));
    const TSharedPtr<FJsonObject>* Binding=nullptr;
    if(Definition->TryGetObjectField(TEXT("binding"),Binding)){
        Part.Type=(*Binding)->GetStringField(TEXT("type"));Part.Record=OverrideRecord.IsEmpty()?(*Binding)->GetStringField(TEXT("record")):OverrideRecord;
        Part.Base=Transform((*Binding)->GetObjectField(TEXT("base")));
        if((*Binding)->HasField(TEXT("parentTransform")))Part.JawBase=Transform((*Binding)->GetObjectField(TEXT("parentTransform")));
        double Number;
        if((*Binding)->TryGetNumberField(TEXT("sign"),Number))Part.Sign=int32(Number);
        if((*Binding)->TryGetNumberField(TEXT("lane"),Number))Part.Lane=int32(Number);
        if((*Binding)->TryGetNumberField(TEXT("station"),Number))Part.Station=int32(Number);
        auto Found=Model->names.find(TCHAR_TO_UTF8(*Part.Record));if(Found!=Model->names.end())Part.RecordIndex=Found->second;
    }
    Part.Last=Part.Type.IsEmpty()?Part.Local:Part.Local*Driver(Part);
    Part.Instance=Component->AddInstance(Part.Last,true);
    if(!Part.Type.IsEmpty())Parts.Add(std::move(Part));
}
void ABrickflowStage::BuildScene()
{
    for(auto C:GeneratedComponents)if(C)C->DestroyComponent();GeneratedComponents.Empty();InstanceGroups.Empty();Parts.Empty();
    for(int32 L=0;L<6;++L)for(int32 S=0;S<3;++S)Centering[L][S].Empty();
    TArray<TSharedPtr<FJsonObject>> PalletPrefab;
    for(const auto& Item:Asset->GetArrayField(TEXT("instances"))){auto Part=Item->AsObject();const TSharedPtr<FJsonObject>* Binding=nullptr;
        if(Part->TryGetObjectField(TEXT("binding"),Binding)&&(*Binding)->GetStringField(TEXT("record"))==TEXT("wood-0"))PalletPrefab.Add(Part);
        else AddPart(Part);
    }
    for(const auto& R:Model->records)if(R.kind=="pallet")for(const auto& Part:PalletPrefab)AddPart(Part,UTF8_TO_TCHAR(R.id.c_str()));
    const auto Brick=Asset->GetObjectField(TEXT("brick"));
    const uint32 Palette[]={0xc39a70,0xa56d4b,0x77503c};
    for(int ID:Model->bricks){const auto& R=Model->records[ID];uint32 RGB=R.good?Palette[R.shade]:R.extreme?0xe0cba7:0x4d382e;
        FLinearColor Tint=FLinearColor::FromSRGBColor(FColor((RGB>>16)&255,(RGB>>8)&255,RGB&255));
        auto Part=MakeShared<FJsonObject>();Part->SetStringField(TEXT("geometry"),Brick->GetStringField(TEXT("geometry")));
        Part->SetArrayField(TEXT("materials"),Brick->GetArrayField(TEXT("materials")));
        Part->SetArrayField(TEXT("color"),{MakeShared<FJsonValueNumber>(Tint.R),MakeShared<FJsonValueNumber>(Tint.G),MakeShared<FJsonValueNumber>(Tint.B)});
        auto Identity=MakeShared<FJsonObject>();Identity->SetArrayField(TEXT("position"),{MakeShared<FJsonValueNumber>(0),MakeShared<FJsonValueNumber>(0),MakeShared<FJsonValueNumber>(0)});
        Identity->SetArrayField(TEXT("rotation"),{MakeShared<FJsonValueNumber>(0),MakeShared<FJsonValueNumber>(0),MakeShared<FJsonValueNumber>(0),MakeShared<FJsonValueNumber>(1)});
        Identity->SetArrayField(TEXT("scale"),{MakeShared<FJsonValueNumber>(1),MakeShared<FJsonValueNumber>(1),MakeShared<FJsonValueNumber>(1)});
        Part->SetObjectField(TEXT("transform"),Identity);auto Bind=MakeShared<FJsonObject>();Bind->SetStringField(TEXT("type"),TEXT("actor"));
        Bind->SetStringField(TEXT("record"),UTF8_TO_TCHAR(R.id.c_str()));Bind->SetObjectField(TEXT("base"),Identity);Part->SetObjectField(TEXT("binding"),Bind);AddPart(Part);
        for(const auto& Track:R.tracks)if(Track.kind=="guided-row-centering"){
            double Z=(Track.from[2]+Track.to[2])/2;int32 BestL=0,BestS=0;double Best=1e20;
            for(int32 L=0;L<6;++L)for(int32 S=0;S<3;++S){double D=FMath::Abs(Model->lanes[L]->stations[S]->z-Z);if(D<Best){Best=D;BestL=L;BestS=S;}}
            Centering[BestL][BestS].AddUnique(TPair<double,double>(Track.start,Track.end));
        }
    }
    for(int32 L=0;L<6;++L)for(int32 S=0;S<3;++S)Centering[L][S].Sort([](auto A,auto B){return A.Key<B.Key;});
    UE_LOG(LogTemp,Display,TEXT("BRICKFLOW_NATIVE_SCENE groups=%d dynamic_parts=%d geometry_assets=%d"),GeneratedComponents.Num(),Parts.Num(),GeneratedMeshes.Num());
}
FTransform ABrickflowStage::Driver(const FPart& Part) const
{
    if(Part.RecordIndex==INDEX_NONE)return Part.Base;
    const auto& R=Model->records[Part.RecordIndex];auto P=Model->pose(Part.RecordIndex,Time);
    if(Time<R.visible)return FTransform(FQuat::Identity,FVector::ZeroVector,FVector::ZeroVector);
    FTransform RootPose=NativePose(P);const auto* Stroke=Model->segment(Part.RecordIndex,Time);
    if(Part.Type==TEXT("actor"))return RootPose;
    if(Part.Type==TEXT("gripperJaw")||Part.Type==TEXT("palletJaw")){
        double Z;
        if(Part.Type==TEXT("palletJaw")){
            double Closed=Stroke&&(Prefix(Stroke->kind,"lift-supported-output")||Prefix(Stroke->kind,"finished-pallet-bridge")||Prefix(Stroke->kind,"lower-pallet-on"))?1:0;
            if(Stroke&&Stroke->kind=="lower-pallet-lifting-frame"&&Time>=Stroke->end)Closed=FMath::Min(1.,(Time-Stroke->end)/.3);
            if(Stroke&&Stroke->kind=="lower-pallet-on-transport-cart"&&Time>=Stroke->end)Closed=1-FMath::Min(1.,(Time-Stroke->end)/.2);
            Z=Part.Sign*(.70-.15*Closed);
        }else{
            bool Held=false;if(Stroke)for(auto PrefixValue:{"lift-36","distribute-2x6","place-on","raise-six","side-pick-and","place-six","lift-complete","transfer-complete","place-guided"})Held|=Prefix(Stroke->kind,PrefixValue);
            if(Stroke&&Prefix(Stroke->kind,"place")&&Time>Stroke->end+.07)Held=false;
            Z=Part.Sign*(Held?.3575:.40);
        }
        FTransform Jaw=Part.JawBase;FVector Position=Jaw.GetTranslation();Position.Y=Z*100;Jaw.SetTranslation(Position);return Jaw*RootPose;
    }
    FTransform Out=Part.Base;
    if(Part.Type==TEXT("sourceBeam")||Part.Type==TEXT("beam")){
        auto Location=Out.GetTranslation();Location.X=P[0]*100;Out.SetTranslation(Location);return Out;
    }
    double Top=R.kind=="rowHead"?3.25:R.kind=="rowPusher"?2.4:R.kind=="dispatch"?4.95:Prefix(R.id,"stacker-")?3.43:4.08;
    if(Part.Type==TEXT("trolley")){Out.SetTranslation(FVector(P[0]*100,P[2]*100,(Top+.07)*100));return Out;}
    if(Part.Type==TEXT("mast")){
        double X=P[0],Y,Z=P[2],SX=.055,SY,SZ=.055;
        if(R.kind=="centeringJaw"){
            TArray<FString> Tokens;Part.Record.ParseIntoArray(Tokens,TEXT("-"));int32 L=FCString::Atoi(*Tokens[1]),S=FCString::Atoi(*Tokens[2]);int32 Side=Part.Record.EndsWith(TEXT("--1"))?-1:1;
            double Back=Model->lanes[L]->stations[S]->z+Side*.62;X=Side<0?52.6:53.4;Y=brickflow::BeltHeight+.08;Z=(P[2]+Back)/2;SX=.035;SY=.035;SZ=FMath::Max(.04,FMath::Abs(P[2]-Back));
        }else if(R.kind=="guideGate"){double Bottom=P[1]+.055;SY=FMath::Max(.02,2.34-Bottom);Y=Bottom+SY/2;Z-=.40;SX=SZ=.035;}
        else if(R.kind=="rejectPusher"){
            int32 L=FCString::Atoi(*Part.Record.RightChop(7));double Back=Model->lanes[L]->z-.53;SZ=FMath::Max(.05,P[2]-Back);Z=Back+SZ/2;Y=brickflow::BeltHeight+.035;SX=SY=.045;
        }else{double Bottom=P[1]+(R.kind=="dispatch"?.38:R.kind=="rowPusher"?.37:.25);SY=FMath::Max(.03,Top-Bottom);Y=Bottom+SY/2;SX=SZ=R.kind=="dispatch"?.12:.055;}
        return FTransform(FQuat::Identity,FVector(X*100,Z*100,Y*100),FVector(SX,SZ,SY));
    }
    if(Part.Type==TEXT("rowPad")||Part.Type==TEXT("rowRod")){
        double D=.42;const auto& Times=Centering[Part.Lane][Part.Station];int32 A=0,B=Times.Num();
        while(A<B){int32 K=(A+B)/2;if(Times[K].Key-.15<=Time)A=K+1;else B=K;}
        if(A>0){auto T=Times[A-1];if(Time<T.Value+.18){
            if(Time<T.Key)D=.42-(.42-.3965)*(Time-(T.Key-.15))/.15;
            else if(Time<=T.Value){double U=(Time-T.Key)/(T.Value-T.Key);U=U*U*(3-2*U);D=.3965-.0365*U;}
            else D=.36+.06*(Time-T.Value)/.18;
        }}
        auto Location=Out.GetTranslation();double Z=Model->lanes[Part.Lane]->stations[Part.Station]->z;
        Location.Y=(Z+Part.Sign*(Part.Type==TEXT("rowPad")?D:(.60+D)/2))*100;Out.SetTranslation(Location);
        if(Part.Type==TEXT("rowRod")){auto Scale=Out.GetScale3D();Scale.Y=.60-D;Out.SetScale3D(Scale);}return Out;
    }
    return Out;
}
void ABrickflowStage::UpdateScene(bool Force)
{
    if(!Model)return;TSet<UInstancedStaticMeshComponent*> Dirty;
    for(auto& Part:Parts){FTransform Current=Part.Local*Driver(Part);if(Force||!Current.Equals(Part.Last,.0001)){
        Part.Component->UpdateInstanceTransform(Part.Instance,Current,true,false,true);Part.Last=Current;Dirty.Add(Part.Component);}}
    for(auto* Component:Dirty)Component->MarkRenderStateDirty();
}
void ABrickflowStage::CreateLighting()
{
    const FVector Locations[]={FVector(1500,-1800,3800),FVector(4000,2500,3000),FVector(6500,-1000,3200)};
    const float Powers[]={1800000,1600000,1800000},Sizes[]={3500,3500,3500};
    for(int32 I=0;I<3;++I){auto* Light=GetWorld()->SpawnActor<ARectLight>(Locations[I],(FVector(Locations[I].X,0,0)-Locations[I]).Rotation());
        auto* Component=Cast<URectLightComponent>(Light->GetLightComponent());Component->SetMobility(EComponentMobility::Movable);
        Component->SetAttenuationRadius(20000);Component->SetIntensity(Powers[I]);Component->SetSourceWidth(Sizes[I]);Component->SetSourceHeight(Sizes[I]);}
    // Invisible studio bounce fills keep the input stacks and profile view readable.
    const FVector FillLocations[]={FVector(-800,-600,1000),FVector(2600,-800,650)};
    const FVector FillTargets[]={FVector(-1300,0,120),FVector(2150,-800,165)};
    for(int32 I=0;I<2;++I){
        auto* Light=GetWorld()->SpawnActor<ARectLight>(FillLocations[I],(FillTargets[I]-FillLocations[I]).Rotation());
        auto* C=Cast<URectLightComponent>(Light->GetLightComponent());C->SetMobility(EComponentMobility::Movable);
        C->SetAttenuationRadius(I==0?3000:1500);C->SetIntensity(I==0?180000:100000);
        C->SetSourceWidth(I==0?1400:800);C->SetSourceHeight(600);C->SetCastShadows(false);
    }
    auto* Sky=GetWorld()->SpawnActor<ASkyLight>();Sky->GetLightComponent()->SetIntensity(.45f);Sky->GetLightComponent()->SetMobility(EComponentMobility::Movable);
    auto* Volume=GetWorld()->SpawnActor<APostProcessVolume>();Volume->bUnbound=true;auto& S=Volume->Settings;
    S.bOverride_AutoExposureMinBrightness=true;S.bOverride_AutoExposureMaxBrightness=true;S.AutoExposureMinBrightness=1;S.AutoExposureMaxBrightness=1;
    S.bOverride_AutoExposureBias=true;S.AutoExposureBias=0;
}
