"""Validate an external document profile before starting the service with it."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Validate documents.json and rules.json profile files.')
    parser.add_argument('directory', type=Path, help='Directory containing documents.json and rules.json')
    args = parser.parse_args()
    os.environ['DEAN_CONFIG_DIR'] = str(args.directory.resolve())
    from app.config import load_config
    from app.knowledge import validate_rules
    schemas, rules = load_config()
    validate_rules(rules, schemas)
    print(json.dumps({'valid': True, 'types': sorted(schemas), 'rules_version': rules['version']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
