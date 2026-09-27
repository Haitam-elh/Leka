# Cloud platforms — what LEKA asks for, and what it reads

AWS today; Azure and GCP next, through [the connector framework](framework.md).
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

The synchronisation of these — per region in scope — is the next part of
LEKA-347.

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
