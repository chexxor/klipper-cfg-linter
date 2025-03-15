from setuptools import setup, find_packages

setup(
    name="klipperlint",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pyyaml",
        "requests",
    ],
    extras_require={
        "dev": ["pytest", "pytest-cov", "black", "mypy"],
        "mining": [],
    },
    entry_points={
        'console_scripts': [
        ],
    },
)