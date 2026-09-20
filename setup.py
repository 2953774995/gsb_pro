from setuptools import find_packages, setup

setup(
    name="minipb",
    version="0.1.0",
    description="A mini Protocol Buffers: schema compiler + binary codec (stdlib only)",
    packages=find_packages(include=["minipb*"]),
    python_requires=">=3.8",
    entry_points={"console_scripts": ["minipb=minipb.cli:main"]},
)
