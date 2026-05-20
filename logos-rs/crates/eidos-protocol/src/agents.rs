//! Профили LLM из agents.yaml.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentsConfig {
    pub version: u32,
    #[serde(default)]
    pub default_profile: Option<String>,
    pub profiles: BTreeMap<String, AgentProfile>,
    #[serde(default)]
    pub tool_routing: Option<ToolRoutingConfig>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentProfile {
    pub base_url: String,
    #[serde(default)]
    pub api_key_env: Option<String>,
    #[serde(default)]
    pub api_key_fallback_envs: Vec<String>,
    pub model: String,
    #[serde(default = "default_timeout")]
    pub read_timeout_sec: f64,
    #[serde(default)]
    pub omit_authorization_header: bool,
}

fn default_timeout() -> f64 {
    120.0
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ToolRoutingConfig {
    #[serde(default)]
    pub defaults: ToolRoutingDefaults,
    #[serde(default)]
    pub groups: BTreeMap<String, ToolRouteGroup>,
    #[serde(default)]
    pub tools: BTreeMap<String, ToolRouteEntry>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ToolRoutingDefaults {
    #[serde(default)]
    pub tool_round_profile: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolRouteGroup {
    pub profile: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolRouteEntry {
    #[serde(default)]
    pub group: String,
    #[serde(default)]
    pub profile: String,
}
