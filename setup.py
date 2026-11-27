from setuptools import setup, find_packages

from opskestrel import __version__

# Read the contents of your requirements.txt file
with open("requirements.txt") as f:
    required = f.read().splitlines()

# Read the contents of your README.md file for the project description
with open("README.md", "r", encoding="utf-8") as readme_file:
    long_description = readme_file.read()

setup(
    name="opskestrel",
    version=__version__,
    packages=find_packages(),
    python_requires=">=3.9,<3.13",
    include_package_data=False,
    install_requires=required,  # Add dependencies here
    entry_points={
        "console_scripts": [
            "operate=operate.main:main_entry",
            "opskestrel=opskestrel.cli:main",
        ],
    },
    package_data={
        # Include the file in the operate.models.weights package
        "operate.models.weights": ["best.pt"],
        "opskestrel": [
            "console_static/*",
            "console_static/assets/*",
        ],
    },
    long_description=long_description,  # Add project description here
    long_description_content_type="text/markdown",  # Specify Markdown format
    # include any other necessary setup options here
)
