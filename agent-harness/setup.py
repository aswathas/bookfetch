from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-bookfetch",
    version="0.1.0",
    description="Fetch any book by name: MCP server + CLI over libgen and open-access fallbacks",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    package_data={
        "cli_anything.bookfetch": [
            "skills/*.md",
            "tests/fixtures/*",
        ]
    },
    install_requires=["click>=8.1", "mcp>=1.2", "PyYAML>=6.0"],
    entry_points={
        "console_scripts": [
            "cli-anything-bookfetch=cli_anything.bookfetch.bookfetch_cli:main",
            "bookfetch-mcp=cli_anything.bookfetch.mcp_server:main",
        ]
    },
    python_requires=">=3.9",
)
