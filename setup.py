from setuptools import setup, find_packages

setup(
    name="networking-tool",
    version="1.0.0",
    description="Networking tool based on 'Never Eat Alone' by Keith Ferrazzi",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "click>=8.0",
        "rich>=13.0",
    ],
    entry_points={
        "console_scripts": [
            "network=networking_tool.cli:cli",
        ],
    },
)
