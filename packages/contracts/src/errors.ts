// SPDX-License-Identifier: Apache-2.0
/** A document failed version, schema, or semantic validation. */
export class ContractError extends Error {
  readonly contract: string;
  readonly issues: string[];

  constructor(contract: string, issues: string[]) {
    super(`${contract}: ${issues.join("; ")}`);
    this.name = "ContractError";
    this.contract = contract;
    this.issues = issues;
  }
}

/** The document's schema_version is missing, malformed, or unsupported. */
export class ContractVersionError extends ContractError {
  constructor(contract: string, issues: string[]) {
    super(contract, issues);
    this.name = "ContractVersionError";
  }
}
