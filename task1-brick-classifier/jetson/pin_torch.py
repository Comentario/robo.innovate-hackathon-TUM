"""Print pip constraints for the torch / torchvision already in the image."""

from importlib import metadata

for package in ("torch", "torchvision"):
    try:
        print(f"{package}=={metadata.version(package)}")
    except metadata.PackageNotFoundError:
        pass
