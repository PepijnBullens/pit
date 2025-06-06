from setuptools import setup, find_packages

setup(
    name="pit",
    version="0.1",
    packages=find_packages(),
    install_requires=["requests"],
    entry_points={
        "console_scripts": [
            "pit = pit.cli:main",  # 'pit' is the CLI command, points to main() in pit/cli.py
        ],
    },
    author="Pepijn Bullens",
    description="A simple git-like CLI tool",
    python_requires=">=3.7",
)
