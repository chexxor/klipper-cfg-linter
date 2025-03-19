"""
Main entry point for the Klipper config linter CLI.
"""

import sys
import click
from pathlib import Path
from typing import Optional
import logging

from .klipper_config_linter import KlipperLinter, create_configured_linter
from .config import LinterConfig
from .klipper_config_parser import export_to_json, parse_config_file, read_file_content

@click.command()
@click.argument('config_file', type=click.Path(exists=True, path_type=Path))
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--strict', '-s', is_flag=True, help='Enable strict checking')
@click.option('--config', '-c', type=click.Path(exists=True, path_type=Path),
              help='Path to linter configuration file')
@click.option('--export-config-to-json-file', '-j', type=click.Path(), help='Export parsed config to JSON file')
def main(config_file: Path, verbose: bool, strict: bool, config: Optional[Path], export_config_to_json_file: Optional[Path]) -> None:
    """Lint a Klipper configuration file for common issues and errors."""
    try:
        # Configure logging
        log_level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            format="%(levelname)s: %(message)s",
            level=log_level
        )
        logger = logging.getLogger(__name__)

        logger.info("Loading configuration file: %s", config_file)
        logger.debug("Verbose mode enabled")
        logger.debug("Strict mode: %s", strict)

        linter_config = LinterConfig.from_file(config) if config else LinterConfig()
        linter_config.verbose = verbose
        linter_config.strict = strict

        linter = create_configured_linter(linter_config)
        parsed_config = parse_config_file(read_file_content(config_file), str(config_file))

        # Export to JSON file, if specified
        if export_config_to_json_file:
            logger.debug("Parsed sections: %s", list(parsed_config.sections.keys()))
            logger.debug("Parsed includes: %s", parsed_config.includes)
            export_to_json(parsed_config, export_config_to_json_file)
            click.echo(f"Exported configuration to {export_config_to_json_file}")
            return

        issues = linter.lint(parsed_config)

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