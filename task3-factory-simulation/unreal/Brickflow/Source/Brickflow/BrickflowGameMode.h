#pragma once
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "BrickflowGameMode.generated.h"

UCLASS()
class BRICKFLOW_API ABrickflowGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    ABrickflowGameMode();
    virtual void StartPlay() override;
};
