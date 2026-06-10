"""Setup script for RaceCraft Desktop"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="racecraft-desktop",
    version="0.1.0",
    author="RaceCraft Team",
    description="Cross-platform racing simulator telemetry collection daemon",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/racecraft-desktop",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.11",
    install_requires=[
        "pydantic>=2.0",
        "msgpack>=1.0",
        "pyirsdk>=1.3",
        "httpx>=0.24",
        "asyncio-dgram>=2.1",
        "aiofiles>=23.0",
        "fastapi>=0.100",
        "uvicorn[standard]>=0.23",
        "websockets>=11.0",
        "PyQt6>=6.5",
        "qasync>=0.24",
        "keyring>=24.0",
        "cryptography>=41.0",
        "psutil>=5.9",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "racecraft=racecraft.app:main",
        ],
    },
)
