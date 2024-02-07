from distutils.core import setup

from setuptools import find_packages

setup(
    name="chmoker",
    version="0.1.0",
    author="Flipper & Community",
    author_email="hello@flipperzero.one",
    url="https://github.com/flipperdevices/chmocker",
    python_requires=">=3.11",
    install_requires=[
        "dockerfile-parse==2.0.1",
        "validators==0.22.0",
        "termcolor==2.4.0"
    ],
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "chmoker = chmoker.main:main",
        ],
    },
)
