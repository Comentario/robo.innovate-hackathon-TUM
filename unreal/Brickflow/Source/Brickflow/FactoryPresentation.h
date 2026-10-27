#pragma once
#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Styling/SlateTypes.h"

class ABrickflowStage;
class SFactoryPresentation : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SFactoryPresentation){}SLATE_ARGUMENT(TWeakObjectPtr<ABrickflowStage>,Stage)SLATE_END_ARGS()
    void Construct(const FArguments& Arguments);
private:
    TWeakObjectPtr<ABrickflowStage> Stage;
    FSlateBrush Card,Panel;
    FButtonStyle ButtonStyle;
    TSharedRef<SWidget> MetricCard(int32 Index,const FString& Label,const FString& Caption);
    TSharedRef<SWidget> Button(const FString& Label,TFunction<void()> Action);
};
