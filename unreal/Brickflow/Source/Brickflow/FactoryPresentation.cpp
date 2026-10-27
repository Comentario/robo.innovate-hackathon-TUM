#include "FactoryPresentation.h"
#include "BrickflowStage.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Framework/Application/SlateApplication.h"
#include "UnrealClient.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SComboButton.h"
#include "Widgets/Input/SSlider.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SDPIScaler.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

namespace {
const FLinearColor Ink(.90,.94,.96,1),Muted(.46,.55,.61,1),Accent(.52,.88,.69,1);
FSlateFontInfo Font(int32 Size,bool Bold=false){return FCoreStyle::GetDefaultFontStyle(Bold?TEXT("Bold"):TEXT("Regular"),Size);}
}
TSharedRef<SWidget> SFactoryPresentation::Button(const FString& Label,TFunction<void()> Action)
{
    return SNew(SButton).ButtonStyle(&ButtonStyle).ContentPadding(FMargin(16,10))
        .OnClicked_Lambda([Action]{Action();return FReply::Handled();})
        [SNew(STextBlock).Text(FText::FromString(Label)).Font(Font(12)).ColorAndOpacity(Ink)];
}
TSharedRef<SWidget> SFactoryPresentation::MetricCard(int32 Index,const FString& Label,const FString& Caption)
{
    return SNew(SBorder).BorderImage(&Card).Padding(FMargin(24,19))[
        SNew(SVerticalBox)
        +SVerticalBox::Slot().AutoHeight()[SNew(STextBlock).Text(FText::FromString(Label)).Font(Font(11)).ColorAndOpacity(Muted)]
        +SVerticalBox::Slot().AutoHeight().Padding(0,8,0,5)[SNew(STextBlock).Font(Font(42,true)).ColorAndOpacity(Index==0?Accent:Ink)
            .Text_Lambda([this,Index]{return FText::FromString(Stage.IsValid()?Stage->Metric(Index):TEXT("—"));})]
        +SVerticalBox::Slot().AutoHeight()[SNew(STextBlock).Text(FText::FromString(Caption)).Font(Font(11)).ColorAndOpacity(Muted)]
    ];
}
void SFactoryPresentation::Construct(const FArguments& Arguments)
{
    Stage=Arguments._Stage;
    Card=FSlateRoundedBoxBrush(FLinearColor(.018,.027,.038,.94),10.f);
    Panel=FSlateRoundedBoxBrush(FLinearColor(.012,.019,.028,.97),12.f);
    ButtonStyle=FButtonStyle().SetNormal(FSlateRoundedBoxBrush(FLinearColor(.04,.06,.075,.9),6.f))
        .SetHovered(FSlateRoundedBoxBrush(FLinearColor(.07,.12,.13,1),6.f))
        .SetPressed(FSlateRoundedBoxBrush(FLinearColor(.10,.20,.19,1),6.f));
    auto Chapters=SNew(SHorizontalBox);
    const FString Names[]={TEXT("Overview"),TEXT("Perception"),TEXT("Blending"),TEXT("Formation"),TEXT("Dispatch"),TEXT("Evidence")};
    for(int32 I=0;I<6;++I)Chapters->AddSlot().AutoWidth().Padding(0,0,7,0)[
        SNew(SButton).ButtonStyle(&ButtonStyle).ContentPadding(FMargin(17,11))
        .OnClicked_Lambda([this,I]{if(Stage.IsValid())Stage->SelectChapter(I);return FReply::Handled();})[
            SNew(STextBlock).Text(FText::FromString(Names[I])).Font(Font(12))
            .ColorAndOpacity_Lambda([this,I]{return Stage.IsValid()&&Stage->ActiveChapter()==I?Accent:Muted;})]
    ];
    auto RecipeMenu=[this]()->TSharedRef<SWidget>{
        auto Choices=SNew(SVerticalBox);
        const TPair<FString,FString> Recipes[]={{TEXT("Mixed pallets"),TEXT("mixed")},{TEXT("Single-colour pallets · all shades"),TEXT("single")},
            {TEXT("Warm only"),TEXT("Warm")},{TEXT("Copper only"),TEXT("Copper")},{TEXT("Russet only"),TEXT("Russet")}};
        for(const auto& Recipe:Recipes){FString Mode=Recipe.Value;Choices->AddSlot().AutoHeight()[Button(Recipe.Key,[this,Mode]{if(Stage.IsValid())Stage->QueueRecipe(Mode);FSlateApplication::Get().DismissAllMenus();})];}
        return SNew(SBorder).BorderImage(&Panel).Padding(8)[Choices];
    };
    auto Metrics=SNew(SHorizontalBox);
    Metrics->AddSlot().FillWidth(1).Padding(0,0,10,0)[MetricCard(0,TEXT("ESTIMATED SHIPPED BRICKS/H"),TEXT("Complete output · modeled batch equivalent"))];
    Metrics->AddSlot().FillWidth(1).Padding(0,0,10,0)[MetricCard(1,TEXT("COMPLETED PALLETS/H"),TEXT("560 approved bricks per complete pallet"))];
    Metrics->AddSlot().FillWidth(1).Padding(0,0,10,0)[MetricCard(2,TEXT("INSPECTION PROGRESS"),TEXT("of 28,800 input bricks · one kiln cart"))];
    Metrics->AddSlot().FillWidth(1)[MetricCard(3,TEXT("COMPLETE OUTPUT"),TEXT("Delivered pallets at the current replay time"))];
    ChildSlot[
        SNew(SDPIScaler).DPIScale_Lambda([]{return GEngine&&GEngine->GameViewport&&GEngine->GameViewport->Viewport?
            GEngine->GameViewport->Viewport->GetSizeXY().Y/1080.f:1.f;})[
        SNew(SOverlay)
        +SOverlay::Slot().VAlign(VAlign_Top).Padding(48,30,48,0)[
            SNew(SVerticalBox)
            +SVerticalBox::Slot().AutoHeight()[SNew(SHorizontalBox)
                +SHorizontalBox::Slot().FillWidth(1)[SNew(STextBlock).Text(FText::FromString(TEXT("B R I C K F L O W"))).Font(Font(17,true)).ColorAndOpacity(Accent)]
                +SHorizontalBox::Slot().AutoWidth()[SNew(STextBlock).Text(FText::FromString(TEXT("INTELLIGENT BRICK BLENDING & PALLETIZING"))).Font(Font(11)).ColorAndOpacity(Muted)]]
            +SVerticalBox::Slot().AutoHeight().Padding(0,25,0,0)[SNew(STextBlock)
                .Text_Lambda([this]{
                    const TCHAR* Titles[]={TEXT("Natural variation.\nOne coordinated flow."),TEXT("Every brick.\nA traceable decision."),TEXT("Three shades.\nA deliberate blend."),TEXT("From individual bricks\nto complete layers."),TEXT("Complete pallets.\nCoordinated dispatch."),TEXT("Every result.\nOpen to inspection.")};
                    return FText::FromString(Titles[Stage.IsValid()?Stage->ActiveChapter():0]);
                }).Font(Font(35,true)).ColorAndOpacity(Ink)]
            +SVerticalBox::Slot().AutoHeight().Padding(0,13,0,0)[SNew(STextBlock).Font(Font(10)).ColorAndOpacity(Muted)
                .Text_Lambda([this]{return FText::FromString(Stage.IsValid()?Stage->StatusText():TEXT("Preparing presentation…"));})]
        ]
        +SOverlay::Slot().VAlign(VAlign_Center).HAlign(HAlign_Right).Padding(0,15,48,180)[
            SNew(SBox).WidthOverride(430).HeightOverride(570).Visibility_Lambda([this]{return Stage.IsValid()&&Stage->IsEvidenceOpen()?EVisibility::Visible:EVisibility::Collapsed;})[
                SNew(SBorder).BorderImage(&Panel).Padding(27)[SNew(SVerticalBox)
                    +SVerticalBox::Slot().AutoHeight()[SNew(STextBlock).Text(FText::FromString(TEXT("THE EVIDENCE"))).Font(Font(13,true)).ColorAndOpacity(Accent)]
                    +SVerticalBox::Slot().FillHeight(1).Padding(0,18,0,20)[SNew(SScrollBox)
                        +SScrollBox::Slot()[SNew(STextBlock).Font(Font(13)).ColorAndOpacity(Ink).WrapTextAt(360)
                            .Text_Lambda([this]{return FText::FromString(Stage.IsValid()?Stage->EvidenceText():TEXT(""));})]]
                    +SVerticalBox::Slot().AutoHeight()[Button(TEXT("Close evidence"),[this]{if(Stage.IsValid())Stage->ToggleEvidence();})]
                ]
            ]
        ]
        +SOverlay::Slot().VAlign(VAlign_Bottom).Padding(48,0,48,30)[
            SNew(SVerticalBox)
            +SVerticalBox::Slot().AutoHeight().Padding(0,0,0,12)[Chapters]
            +SVerticalBox::Slot().AutoHeight()[Metrics]
            +SVerticalBox::Slot().AutoHeight().Padding(0,12,0,0)[SNew(SBorder).BorderImage(&Panel).Padding(FMargin(16,11))[
                SNew(SHorizontalBox)
                +SHorizontalBox::Slot().AutoWidth()[SNew(SButton).ButtonStyle(&ButtonStyle).ContentPadding(FMargin(16,9))
                    .OnClicked_Lambda([this]{if(Stage.IsValid())Stage->TogglePlayback();return FReply::Handled();})[
                    SNew(STextBlock).Font(Font(12,true)).ColorAndOpacity(Accent).Text_Lambda([this]{return FText::FromString(Stage.IsValid()&&Stage->IsPlaying()?TEXT("Pause"):TEXT("Play"));})]]
                +SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(18,0)[SNew(STextBlock).Font(Font(12)).ColorAndOpacity(Muted)
                    .Text_Lambda([this]{return FText::FromString(Stage.IsValid()?Stage->ClockText():TEXT("—"));})]
                +SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center).Padding(5,0,20,0)[SNew(SSlider).SliderHandleColor(Accent).SliderBarColor(FLinearColor(.12,.18,.22,1))
                    .Value_Lambda([this]{return Stage.IsValid()?Stage->Progress():0;})
                    .OnValueChanged_Lambda([this](float Value){if(Stage.IsValid())Stage->SeekNormalized(Value);})]
                +SHorizontalBox::Slot().AutoWidth()[SNew(SButton).ButtonStyle(&ButtonStyle).ContentPadding(FMargin(15,9))
                    .OnClicked_Lambda([this]{if(Stage.IsValid())Stage->CycleSpeed();return FReply::Handled();})[
                    SNew(STextBlock).Font(Font(12)).ColorAndOpacity(Ink).Text_Lambda([this]{return FText::FromString(Stage.IsValid()?Stage->SpeedText():TEXT("12×"));})]]
                +SHorizontalBox::Slot().AutoWidth().Padding(12,0,0,0)[Button(TEXT("Restart batch"),[this]{if(Stage.IsValid())Stage->RestartBatch();})]
                +SHorizontalBox::Slot().AutoWidth().Padding(12,0,0,0)[SNew(SComboButton).OnGetMenuContent_Lambda(RecipeMenu)
                    .IsEnabled_Lambda([this]{return Stage.IsValid()&&!Stage->IsBusy();})
                    .ButtonContent()[SNew(STextBlock).Text(FText::FromString(TEXT("Queue recipe"))).Font(Font(12))]]
            ]]
        ]
        ]
    ];
}
