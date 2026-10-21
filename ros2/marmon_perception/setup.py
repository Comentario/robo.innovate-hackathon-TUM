from setuptools import find_packages, setup


setup(
    name="marmon_perception",
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/marmon_perception"]),
        ("share/marmon_perception", ["package.xml", "perception/README.md"]),
        ("share/marmon_perception/config", ["config/fastdds_images.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="Comentario",
    maintainer_email="comentario@users.noreply.github.com",
    description="Unified brick perception ROS 2 node",
    license="MIT",
    entry_points={
        "console_scripts": ["perception_node = perception.ros_node:main"],
    },
)
