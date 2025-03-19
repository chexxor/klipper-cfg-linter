
## Current Functionality

The linter currently supports basic configuration file validation with a few implemented rules. Here's what's working:

### Input Format
The tool accepts Klipper configuration files in the standard format:
```ini
[section_name]
option: value  # Optional comment

[include other_config.cfg]  # Include directive support

[stepper_x]
step_pin: PF0
dir_pin: PF1
microsteps: 16
```

### Implemented Rules
Currently implemented rules include:

1. **Pin Syntax Validation**
   ```ini
   # Valid
   [stepper_x]
   step_pin: PF0
   dir_pin: !PF1

   # Invalid - Will raise error
   [stepper_x]
   step_pin: invalid_pin
   dir_pin: GPIO23
   ```

2. **Section Naming Conventions**
   ```ini
   # Valid
   [stepper_x]
   [extruder]

   # Invalid - Will raise warning
   [Stepper_X]
   [EXTRUDER]
   ```

3. **Required Sections Check**
   ```ini
   # Required
   [printer]
   kinematics: cartesian

   # Missing [printer] section will raise error
   [stepper_x]
   step_pin: PF0
   ```

### Output Format
The linter provides error messages in the following format:
```
Error in section 'stepper_x': Invalid pin format: invalid_pin
Warning in section 'Stepper_X': Section name should be lowercase
Error: Missing required section: printer
```

Each message includes:
- Error severity (Error/Warning)
- Affected section
- Detailed message
- Fix suggestion (when available)

### Command Line Options
```bash
# Basic usage
python -m klipperlint your_printer.cfg

# Basic usage with example config
python -m klipperlint tests/test_configs/example-cartesian.cfg
# Output:
# INFO: Loading configuration file: tests/test_configs/example-cartesian.cfg
# INFO: Loading rules from: /klipper-cfg-linter/klipperlint/rules
# INFO: Loaded 6 rules
# INFO: Starting lint analysis with 7 rules
# INFO: Completed lint analysis. Found 1 total issues
# LintError(message='Extruder extruder requires at least one cooling fan', section='extruder', option=None, severity='error', line_number=None, fix=None)

# Enable verbose output
python -m klipperlint --verbose your_printer.cfg

# Enable strict checking (treats warnings as errors)
python -m klipperlint --strict your_printer.cfg

# Use custom config file
python -m klipperlint --config my_config.yaml your_printer.cfg

# Parses the config file and exports it to a JSON-formatted file
python -m klipperlint tests/test_configs/include.cfg --export-config-to-json-file ./test-include-cfg.json
# test-include-cfg-json:
# {
#     "printer": {
#         "max_velocity": "300"
#     },
#     "extruder": {
#         "heater_pin": "PA1"
#     }
# }

# Collects GitHub issues since specified date,
#   then asks LLM if they are related to config-related errors,
#   storing results in sqlite database. Use DB Browser for SQLite to query results.
python -m klipper_cfg_issue_mining.scripts.collect_data --source github --since 2025-03-01 &> out.txt

# Collects Discourse issues since specified date,
#   then asks LLM if they are related to config-related errors,
#   storing results in sqlite database. Use DB Browser for SQLite to query results.
python -m klipper_cfg_issue_mining.scripts.collect_data --source discourse --since 2025-03-01 &> out.txt
```
