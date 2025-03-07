# Klipper Config Linter

A Python-based linting tool for analyzing and validating Klipper 3D printer configuration files. This tool helps identify common configuration issues, syntax errors, and potential problems in your Klipper config files before deploying them to your printer.

## Features

- Syntax validation for Klipper config files
- Detection of common configuration mistakes
- Validation of pin assignments and hardware configurations
- Check for missing required sections
- Identification of deprecated settings
- Best practices recommendations

## Installation

1. Clone this repository:
```bash
git clone https://github.com/chexxor/klipper-cfg-linter.git
cd klipper-cfg-linter
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Basic usage:
```bash
python -m klipperlint your_printer.cfg
```

Advanced options:
```bash
python -m klipperlint --verbose --strict your_printer.cfg
```

## Configuration

The linter can be configured using a `.klipperlint.yaml` file in your home directory or the current working directory. Example configuration:

```yaml
ignore:
  - deprecated_setting_warning
  - pin_already_used
strict: false
verbose: true
```

## Rules

The linter checks for various issues including:

- Invalid section names
- Duplicate sections
- Missing required parameters
- Invalid pin assignments
- Conflicting settings
- Hardware compatibility issues
- Deprecated configuration options

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Klipper](https://github.com/Klipper3d/klipper) - The 3D printer firmware this tool is designed to work with
- The 3D printing community for their valuable feedback and suggestions

## Support

If you encounter any issues or have questions, please file an issue on the GitHub repository.