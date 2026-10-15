# Mercury v1.0.1

## Fixed

Malformed rounding precision now follows the existing rejected-operation path instead of raising an uncaught conversion exception. Invalid text, nulls, containers and infinite values are rejected. Valid numeric and numeric-string precision, including zero and negative precision, retains its existing behaviour.

The cleaning engine warns and leaves the dataset unchanged when the operation is rejected and no alternative transformation is supplied. Regression tests cover the parser and both rejected and successful engine paths.

## Release packaging

This release contains the application source, bundled frontend assets, configuration example and maintained tests. Datasets, credentials, local databases, runtime files and academic-report drafts are excluded. Configure the application using `.env.example` and install `requirements.txt` as described in `README.md`.

The deployment archive uses the version tag for its top-level directory. CI validation precedes packaging and publication. The CI suite retains its two existing exclusions: `test_pin_and_report_flow_portable` and `test_security_headers_present`; this release does not claim those excluded tests or live provider/browser workflows were verified.

## Compatibility

The fix preserves the parser's existing `None` rejection contract and valid rounding behaviour. No database migration is required.
