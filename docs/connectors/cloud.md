# Cloud platforms — what LEKA asks for, and what it reads

AWS and Azure today; GCP next, through [the connector framework](framework.md).
LEKA-347. **LEKA only reads**: every call is a `Describe`, `List` or `Get`.

---

## AWS

One source is one AWS account.

| | |
|---|---|
| Credentials | an IAM access key (`access_key_id`, `secret_access_key`) — never the root user's (accepted, with a warning) |
| Recommended | a **role** in the account for that key to assume (`role_arn`), with an **`external_id`** its trust policy requires: the key alone then reads nothing, and revoking LEKA is one trust policy |
| Scope | `regions` — the regions to read (`eu-west-3`, …). Empty: every region the account has enabled. The Sources screen offers the enabled ones |
| Config | `role_arn`, `external_id`, `regions` |

### The policy — read-only, and nothing more

Attach to the user (or to the role LEKA assumes):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LekaReadInventory",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:DescribeVpcs",
        "rds:DescribeDBInstances",
        "s3:ListAllMyBuckets",
        "lambda:ListFunctions",
        "eks:ListClusters",
        "eks:DescribeCluster",
        "elasticloadbalancing:DescribeLoadBalancers"
      ],
      "Resource": "*"
    }
  ]
}
```

A service left out of the policy is a **capability left out** at the
connection test, not a failure: the source reads what it may, and says what
it does not. AWS's managed `ReadOnlyAccess` works too, but allows reading
data (objects in S3, items in DynamoDB) that LEKA does not need — prefer
the policy above.

### The role, when the key assumes one

The role's trust policy lets the key's user assume it, with the external id:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::<ACCOUNT OF THE KEY>:user/leka" },
      "Action": "sts:AssumeRole",
      "Condition": { "StringEquals": { "sts:ExternalId": "<EXTERNAL ID>" } }
    }
  ]
}
```

The role is assumed once per connector, for one pass or one test, and its
temporary credentials are never stored.

### What is read

| Capability | AWS | Read by |
|---|---|---|
| `instances` | EC2 instances | `ec2:DescribeInstances` |
| `db_instances` | RDS database instances | `rds:DescribeDBInstances` |
| `buckets` | S3 buckets (the list, never their objects) | `s3:ListAllMyBuckets` |
| `functions` | Lambda functions | `lambda:ListFunctions` |
| `clusters` | EKS clusters | `eks:ListClusters`, `eks:DescribeCluster` |
| `networks` | VPCs | `ec2:DescribeVpcs` |
| `load_balancers` | Application and network load balancers | `elasticloadbalancing:DescribeLoadBalancers` |

### How it is read

Each capability in **every region of the scope** — S3's bucket list, being
global, once — page by page, each resource known by its **ARN** (stable,
unique across accounts and regions), with its region as container. boto3's
dates are stored as text.

**Every pass reads them whole.** AWS has no "changed since" for any of these
inventories, so the connector declares them `listed_whole`: the index keeps
a pass from writing what did not change, and marks gone what is no longer
listed **at every pass** — an instance terminated disappears within the
hour, not at the weekly full pass. A throttled listing stops with
`RATE_LIMITED` and is retried a minute later; what was read stands.

### Diagnostics

| AWS says | LEKA says |
|---|---|
| `InvalidClientTokenId`, `SignatureDoesNotMatch`, `AuthFailure` | `AUTH_INVALID` |
| `ExpiredToken`, `RequestExpired` | `AUTH_EXPIRED` |
| `AccessDenied`, `UnauthorizedOperation` | `PERMISSION_DENIED` — on `AssumeRole`: the trust policy or the external id |
| `Throttling`, `RequestLimitExceeded`, `SlowDown` | `RATE_LIMITED`, back in a minute |
| a 5xx | `PROVIDER_ERROR` |
| no connection, no answer in 10 s | `NETWORK_UNREACHABLE`, `TIMEOUT` |

The key id and the secret are removed from every diagnostic.

### Why boto3 and not `self.http()`

AWS signs every request (SigV4) and each service speaks its own protocol —
reimplementing that over httpx would be a second SDK to maintain, and boto3
is already LEKA's (the S3 object store). What `self.http()` also guards
against — an admin typing an address the server should not call — does not
arise: every endpoint is AWS's own, chosen by region.


---

## Azure

One source is one Microsoft Entra tenant, and the subscriptions it scopes.

| | |
|---|---|
| Credentials | a **service principal**: its application (`client_id`) and a client secret |
| Role | **Reader**, on each subscription LEKA should read — nothing more |
| Scope | `subscriptions` — their ids. Empty: every subscription the service principal can see. The Sources screen offers them |
| Config | `tenant_id`, `subscriptions` |

Create it in one line, per subscription:

```bash
az ad sp create-for-rbac --name leka-reader --role Reader \
  --scopes /subscriptions/<SUBSCRIPTION ID>
# → appId (client_id), password (client_secret), tenant (tenant_id)
```

A secret expires (two years at most): LEKA says `AUTH_EXPIRED` when it has,
and the source goes to `error` at its next pass — renew it and replace the
credentials.

### What is read

Azure Resource Manager's resource list, **filtered by type**, in every
subscription of the scope, following `nextLink`. Every resource is known by
its ARM id, **lower-cased** (Azure's ids are case-insensitive), with its
subscription as container.

| Capability | Azure resource types |
|---|---|
| `instances` | `Microsoft.Compute/virtualMachines`, `…/virtualMachineScaleSets` |
| `db_instances` | `Microsoft.Sql/servers/databases`, `Microsoft.DBforPostgreSQL/flexibleServers`, `Microsoft.DBforMySQL/flexibleServers`, `Microsoft.DocumentDB/databaseAccounts` |
| `buckets` | `Microsoft.Storage/storageAccounts` |
| `functions` | `Microsoft.Web/sites` (function and web apps) |
| `clusters` | `Microsoft.ContainerService/managedClusters` |
| `networks` | `Microsoft.Network/virtualNetworks` |
| `load_balancers` | `Microsoft.Network/loadBalancers`, `…/applicationGateways` |

Like AWS, every capability is **listed whole** at every pass: nothing
unchanged is written, and a deleted resource is gone at the next pass. The
Reader role opens the whole list at once, so the connection test asks once.

**Every call to Resource Manager is a GET.** The one POST is the token
request to Microsoft's identity platform (`login.microsoftonline.com`) — an
exchange of the secret for a token, touching nothing of the customer's. The
token is asked for once per connection test or pass, never stored.

### Diagnostics

| Microsoft says | LEKA says |
|---|---|
| `AADSTS7000215` (wrong secret), `AADSTS700016` (unknown application) | `AUTH_INVALID` |
| `AADSTS7000222` (secret expired) | `AUTH_EXPIRED` |
| `AADSTS90002` (no such tenant) | `NOT_FOUND` |
| a subscription in scope it cannot see | `NOT_FOUND`, naming it — check the Reader role |
| 403 on the resource list | the capabilities are left out |
| 429 | `RATE_LIMITED`, with Azure's `Retry-After` |

Azure's own mark is not shown: Microsoft asks icon sets not to carry it. The
Sources screen draws a plain cloud in Azure's blue.
