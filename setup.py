"""Compatibility installer for Python environments with older pip/setuptools."""

from setuptools import find_packages, setup


setup(
    name="bankhuman",
    version="0.1.0",
    description="A local personal-finance registry for bank accounts and investments.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    install_requires=["pandas>=2.0", "openpyxl>=3.1", "xlrd>=2.0"],
    packages=find_packages(include=["bankhuman", "bankhuman.*"]),
    entry_points={"console_scripts": ["bankhuman=bankhuman.cli:main"]},
)
