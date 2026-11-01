#include "BrickflowGameMode.h"
#include "BrickflowStage.h"
#include "Engine/World.h"
#include "Internationalization/Internationalization.h"

ABrickflowGameMode::ABrickflowGameMode()
{
    DefaultPawnClass = nullptr;
}

void ABrickflowGameMode::StartPlay()
{
    Super::StartPlay();
    FInternationalization::Get().SetCurrentCulture(TEXT("en-US"));
    GetWorld()->SpawnActor<ABrickflowStage>();
}
