import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="p4cmd",
    version="1.2.1",
    author="Niels Vaes",
    license='MIT',
    author_email="nielsvaes@gmail.com",
    description="Simple P4 python module",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nielsvaes/p4cmd",
    install_requires=[],
    packages=setuptools.find_packages(),
    classifiers=[
        "Operating System :: OS Independent",
    ]
)