from setuptools import setup, find_packages

from soc_agent import __version__

# Read the contents of your requirements.txt file
with open("requirements.txt") as f:
    required = f.read().splitlines()

# Read the contents of your README.md file for the project description
with open("README.md", "r", encoding="utf-8") as readme_file:
    long_description = readme_file.read()

setup(
    name="self-operating-computer",
    version=__version__,
    packages=find_packages(),
    python_requires=">=3.9,<3.13",
    include_package_data=True,
    install_requires=required,  # Add dependencies here
    entry_points={
        "console_scripts": [
            "operate=operate.main:main_entry",
            "soc-agent=soc_agent.cli:main",
        ],
    },
    package_data={
        # Include the file in the operate.models.weights package
        "operate.models.weights": ["best.pt"],
    },
    long_description=long_description,  # Add project description here
    long_description_content_type="text/markdown",  # Specify Markdown format
    # include any other necessary setup options here
)
