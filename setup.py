from setuptools import setup, find_packages

setup(
    name="moonspeak",
    version="0.1.0",
    description="AI-Powered English Pronunciation Coach for Kids",
    author="月弦 (Moon)",
    author_email="",
    url="https://github.com/pengyuexian/MoonSpeak",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=[
        "azure-cognitiveservices-speech>=1.49.0",
        "whisper-cli>=0.0.5",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Education",
        "Topic :: Education :: Language",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
    ],
    license="MIT",
)
