# Klipper Config Linter

A Python-based linting tool for analyzing and validating Klipper 3D printer configuration files. This tool helps identify common configuration issues, syntax errors, and potential problems in your Klipper config files before deploying them to your printer.

> **⚠️ WARNING: Project Under Heavy Development**
>
> This project is currently in early development stages and is not ready for production use. You may encounter bugs, incomplete features, and breaking changes.
>
> **Note:** Currently, there are very few implemented linting rules, so the tool will not be helpful for validating printer configurations yet. Please check back later as we continue to develop and implement more rules.

## Planned Features

The following features are planned but may not be fully implemented yet:

- Syntax validation for Klipper config files
- Detection of common configuration mistakes
- Validation of pin assignments and hardware configurations
- Check for missing required sections
- Identification of deprecated settings
- Best practices recommendations

## Installation

To do: Confirm these steps.

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

To do: Confirm these.

Basic usage:
```bash
python -m klipperlint your_printer.cfg
```

Advanced options:
```bash
python -m klipperlint --verbose --strict your_printer.cfg
```

## Development Status

The project is currently focusing on:
1. Building a robust parser for Klipper configuration files
2. Implementing core linting rules
3. Gathering community feedback on most needed validations

We welcome contributions but please note that the codebase is rapidly changing.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Klipper](https://github.com/Klipper3d/klipper) - The 3D printer firmware this tool is designed to work with
- The 3D printing community for their valuable feedback and suggestions

## Support

If you encounter any issues or have questions, please file an issue on the GitHub repository.