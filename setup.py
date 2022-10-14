import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

data_files_to_include = ["*.png"]

setuptools.setup(
    name="p4cmd",
    version="1.3.6",
    author="Niels Vaes",
    license='MIT',
    author_email="nielsvaes@gmail.com",
    description="Simple P4 python module",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nielsvaes/p4cmd",
    install_requires=[],
    packages=setuptools.find_packages(),
    package_data={
        "": data_files_to_include,
    },
    classifiers=[
        "Operating System :: OS Independent",
    ]
)