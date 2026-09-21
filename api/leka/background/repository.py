"""Every database query of the background module.

Arrives with the deliverable that first needs one: publishing an event, then
claiming and finishing a run. Events go through WorkspaceScopedRepository;
job_runs is tenant-free by design and is filtered explicitly — see JobRun.
"""
