"""
Main entry point for the Klipper config linter CLI.
"""

import sys
import click
from pathlib import Path
from typing import Optional

from .linter import KlipperLinter
from .config import LinterConfig

@click.command()
@click.argument('config_file', type=click.Path(exists=True, path_type=Path))
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--strict', '-s', is_flag=True, help='Enable strict checking')
@click.option('--config', '-c', type=click.Path(exists=True, path_type=Path),
              help='Path to linter configuration file')
def main(config_file: Path, verbose: bool, strict: bool, config: Optional[Path]) -> None:
    """Lint a Klipper configuration file for common issues and errors."""
    try:
        linter_config = LinterConfig.from_file(config) if config else LinterConfig()
        linter_config.verbose = verbose
        linter_config.strict = strict

        linter = KlipperLinter(linter_config)
        issues = linter.lint_file(config_file)

        if issues:
            for issue in issues:
                click.echo(str(issue))
            sys.exit(1)
        else:
            click.echo("No issues found!")
            sys.exit(0)

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)

if __name__ == '__main__':
    main()