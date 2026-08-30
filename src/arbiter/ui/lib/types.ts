export type JsonRecord = Record<string, unknown>;

export interface PortOwner extends JsonRecord {
  port: number;
  protocol?: string;
  address?: string;
  pid?: number | null;
  process?: string | null;
  owner_type?: string;
  project_name?: string | null;
  project?: string | null;
  service?: string | null;
  container_name?: string | null;
  container?: string | null;
  source?: string;
}

export interface Project extends JsonRecord {
  id: string;
  name: string;
  path: string;
  services?: string[];
  ports?: Array<JsonRecord>;
  compose_files?: string[];
  dockerfiles?: string[];
  registered?: boolean;
}

export interface Container extends JsonRecord {
  id: string;
  name: string;
  image: string;
  state: string;
  status?: string;
  compose_project?: string | null;
  compose_service?: string | null;
  ports?: Array<JsonRecord>;
  networks?: string[];
}

export interface Approval extends JsonRecord {
  id: string;
  action: string;
  summary: string;
  risk: string;
  status: string;
  arguments?: JsonRecord;
  created_at?: string;
}

export interface ActionRecord extends JsonRecord {
  id: string;
  request_id?: string;
  action: string;
  risk: string;
  status: string;
  result?: unknown;
  verification?: unknown;
  error?: string | null;
}

export interface SystemEvent extends JsonRecord {
  id?: string;
  timestamp?: string;
  created_at?: string;
  source?: string;
  kind?: string;
  event_type?: string;
  type?: string;
  resource_type?: string;
  action?: string;
  resource?: string;
  resource_id?: string;
  message?: string;
  detail?: string;
}

export interface TopologyNode extends JsonRecord {
  id: string;
  resource_type: string;
  label: string;
  status?: string | null;
  metadata?: JsonRecord;
  attributes?: JsonRecord;
  evidence?: string[];
}

export interface TopologyEdge extends JsonRecord {
  source: string;
  target: string;
  relationship: string;
}

export interface TopologyGraph extends JsonRecord {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface RuntimeCapability extends JsonRecord {
  name: string;
  available?: boolean;
  support?: string;
  detail?: string | null;
  status?: string;
  version?: string | null;
  executable?: string | null;
  capabilities?: string[];
}

export interface ProjectFile extends JsonRecord {
  path: string;
  kind?: string;
  size?: number;
  modified_at?: string;
}

export interface FileContent extends JsonRecord {
  path: string;
  content: string;
  sha256: string;
  kind?: string;
}

export interface ReadinessGate extends JsonRecord {
  probe_type: "tcp_port" | "http_get" | "docker_health";
  host?: string;
  port?: number | null;
  path?: string | null;
  timeout_seconds?: number;
  retry_interval_seconds?: number;
  expected_status?: number;
  service?: string | null;
}

export interface ReadinessProbeResult extends JsonRecord {
  service?: string | null;
  probe_type: string;
  target: string;
  healthy: boolean;
  latency_ms?: number;
  status_code?: number | null;
  message?: string | null;
  checked_at?: string;
}

export interface StackProjectMember extends JsonRecord {
  project_id: string;
  project_name: string;
  env_overrides?: Record<string, string>;
  depends_on?: string[];
  readiness_gates?: ReadinessGate[];
  boot_stage?: number;
}

export interface StackPreset extends JsonRecord {
  id: string;
  name: string;
  description?: string | null;
  projects: StackProjectMember[];
  is_active: boolean;
  status: string;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface BootOrderStage extends JsonRecord {
  stage: number;
  projects: string[];
  readiness_gates?: ReadinessGate[];
  description?: string | null;
}

export interface StackBootPlan extends JsonRecord {
  stack_id: string;
  stack_name: string;
  stages: BootOrderStage[];
  total_stages: number;
  dependencies_valid: boolean;
  cycle_detected: boolean;
  error?: string | null;
}

export interface StackSwitchResult extends JsonRecord {
  id: string;
  previous_stack_id?: string | null;
  target_stack_id: string;
  stopped_projects: string[];
  started_projects: string[];
  port_reconciliations: Array<JsonRecord>;
  env_changes: Array<JsonRecord>;
  readiness_results: ReadinessProbeResult[];
  status: string;
  verified: boolean;
  error?: string | null;
}

