//! Контракты данных Эйдоса (совместимы с Python `kernel/` и `cli/`).
//!
//! JSON Schema: `logos-rs/schemas/*.json` (в т.ч. `semantic-principle.json`).

pub mod agents;
pub mod chat;
pub mod episodic;
pub mod semantic;
pub mod working;

pub const SCHEMAS_DIR: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../schemas");
