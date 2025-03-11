from setuptools import setup, find_packages

setup(
    name="klipperlint",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        # Existing dependencies
        "pyyaml",
        # New dependencies for rule mining
        "requests",
        "beautifulsoup4",
        "discord.py",
        "praw",
        "pandas",
        "scikit-learn",
    ],
    extras_require={
        "dev": ["pytest", "pytest-cov", "black", "mypy"],
        "mining": ["jupyter", "matplotlib", "seaborn"],
    },
    entry_points={
        'console_scripts': [
            'klipperlint-collect=klipperlint.mining.scripts.collect_data:main',
        ],
    },
)