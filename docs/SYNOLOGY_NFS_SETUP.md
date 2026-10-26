# Synology NAS Setup for NFS

## Accessing Your Synology DSM

1. Go to http://valhalla.local:5000 and log in
2. You'll need to enable NFS and create a shared folder for AI models

## Step 1: Enable NFS Service

1. In DSM, go to **Control Panel** → **File Services** → **NFS** tab
2. Check "Enable NFS service"
3. Click **Apply**

## Step 2: Create Shared Folder

1. Go to **Control Panel** → **Shared Folder**
2. Click **Create** → **Create Shared Folder**
3. Name it: `ai_models`
4. Description: "AI model storage for Local AI cluster"
5. Location: Choose your volume (usually Volume 1)
6. Click **Next** through the options
7. Click **Apply**

## Step 3: Configure NFS Permissions

1. Still in **Shared Folder**, select `ai_models`
2. Click **Edit** → **NFS Permissions** tab
3. Click **Create**
4. Configure NFS rule:
   - **Hostname or IP**: `*` (or specify your subnet like `192.168.1.0/24`)
   - **Privilege**: Read/Write
   - **Squash**: Map all users to admin
   - **Security**: sys
   - Check "Enable asynchronous"
   - Check "Allow connections from non-privileged ports"
5. Click **OK**

## Step 4: Verify NFS Export

On either the Raspberry Pi or Jetson, test the NFS mount:

```bash
# Check what's exported
showmount -e valhalla.local

# Should show something like:
# Export list for valhalla.local:
# /volume1/ai_models *
```

## Step 5: Update Configuration Files

Your NFS mount path will be:
```
valhalla.local:/volume1/ai_models
```

The configuration files have been updated to use `valhalla.local` instead of an IP address.

## Step 6: Test NFS Mount

On both machines, test mounting:

```bash
# Create mount point
sudo mkdir -p /mnt/ai_models

# Test mount
sudo mount -t nfs valhalla.local:/volume1/ai_models /mnt/ai_models

# Check if it worked
ls -la /mnt/ai_models

# If successful, unmount for now
sudo umount /mnt/ai_models
```

## Troubleshooting

### If mount fails with "Permission denied":
1. Check NFS permissions in Synology
2. Make sure "Map all users to admin" is selected
3. Try using IP address instead of hostname

### If "showmount" can't reach the NAS:
1. Check firewall settings on Synology
2. Make sure NFS ports are open (2049, 111, 892)
3. Try: `ping valhalla.local`

### Finding the IP address:
If you need the actual IP instead of hostname:
```bash
# On Mac/Linux
nslookup valhalla.local

# Or in Synology DSM:
# Control Panel → Network → Network Interface
```

## Security Note

The NFS setup above allows read/write access from your local network. Make sure:
1. Your Synology firewall is configured
2. The NFS share is only accessible from your local network
3. Consider restricting the hostname/IP in NFS permissions to just your cluster machines

Once NFS is set up on your Synology, the scripts will automatically mount it on both machines!
