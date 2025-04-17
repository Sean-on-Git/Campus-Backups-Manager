## Campus Local Backups Remover
### Connects ServiceNow with local data backups for easy archival and removal of locally backed up data

#### Configuration
Location of of backups, items to be deleted, and service now instance are controlled by "config.json"

Example layout:
```
{
    "instance": "example.service-now.com",
    "backups_location": "C:\\backups",
    "deletion_location": "C:\\backups\\_MARKED-FOR-DELETION"
}
```

Currently, "config.json" is read from your current working directory when running the application.

A static location or command line argument may be added later to specify config location.

#### Logging
Log files are stored in same directory as executable.
Errors are written to "error.log"
Debuggin logs are written to "debug.log"
Currently debugging is enabled by default with no flags to disable.