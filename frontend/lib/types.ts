export type Tenant = {
  id: string;
  name: string;
  tools_enabled: string[];
};

export type TenantsResponse = {
  default_tenant: string | null;
  tenants: Tenant[];
  error?: string;
};
