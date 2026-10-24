# SPDX-License-Identifier: AGPL-3.0-or-later
<#
  show_progress_dialog.ps1 - open the shell's legacy file-operation progress dialog with a chosen
  operation, so its header animation plays for as long as needed (for reference recordings).

  Written 5 Oct 2026 from analysis of shell32/windows.storage. 6 Oct: fixed call order after the first
  test failed with E_UNEXPECTED (SetOperation was called before StartProgressDialog).
  Tested 6 Oct 2026 on the Win7 SP1 VM with -Action 5: works.
  Target: Windows 7 or Vista guest (PowerShell 2.0 is enough). Run from an STA console:

      powershell -sta -ExecutionPolicy Bypass -File show_progress_dialog.ps1 -Action 5 -Seconds 40

  -Action is the SPACTION value. The shell picks the header animation (FTR) from it via the
  operation table in shell32 (Win7 x64 file offset 0x488b20), which is indexed by SPACTION:

      0 NONE ("Processing")    -> FTR 200     7 CALCULATING        -> FTR 200
      1 MOVING                 -> FTR 202     8 UPLOADING          -> FTR 200
      2 COPYING                -> FTR 201     9 SEARCHING_FILES    -> FTR 200
      3 RECYCLING              -> FTR 204    10 DELETING           -> FTR 205
      4 APPLYINGATTRIBS        -> FTR 203    11 RENAMING           -> FTR 200
      5 DOWNLOADING            -> FTR 200    12 FORMATTING         -> FTR 200
      6 SEARCHING_INTERNET     -> FTR 200    13 COPY_MOVING        -> FTR 202

  The dialog may take a second or two to appear (the shell delays it). Keep the pointer off it.
#>
param([int]$Action = 5, [int]$Seconds = 40)

$code = @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("0C9FB851-E5C9-43EB-A370-F0677B13874C"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IOperationsProgressDialog {
    void StartProgressDialog(IntPtr hwndOwner, uint flags);
    void StopProgressDialog();
    void SetOperation(int action);
    void SetMode(uint mode);
    void UpdateProgress(ulong pointsCurrent, ulong pointsTotal, ulong sizeCurrent, ulong sizeTotal,
                        ulong itemsCurrent, ulong itemsTotal);
    void UpdateLocations(IntPtr source, IntPtr target, IntPtr item);
    void ResetTimer();
    void PauseTimer();
    void ResumeTimer();
    void GetMilliseconds(out ulong elapsed, out ulong remaining);
    void GetOperationStatus(out int status);
}

public static class FtrProgress {
    delegate void Call();
    static void Step(string name, Call c) {
        try { c(); }
        catch (Exception e) { throw new Exception(name + " failed: " + e.Message, e); }
    }
    public static void Run(int action, int seconds) {
        Type t = Type.GetTypeFromCLSID(new Guid("F8383852-FCD3-11D1-A6B9-006097DF5BD4")); // CLSID_ProgressDialog
        IOperationsProgressDialog d = (IOperationsProgressDialog)Activator.CreateInstance(t);
        // Order matters: Win7 shell32 returns E_UNEXPECTED from SetOperation, SetMode and
        // UpdateProgress until StartProgressDialog has run (checked in its code, 6 Oct 2026).
        Step("StartProgressDialog", delegate { d.StartProgressDialog(IntPtr.Zero, 0); });  // OPPROGDLG_DEFAULT
        Step("SetOperation", delegate { d.SetOperation(action); });
        Step("SetMode", delegate { d.SetMode(1); });                                        // PDM_RUN
        ulong total = (ulong)seconds * 10;
        for (ulong i = 0; i < total; i++) {
            d.UpdateProgress(i, total, i * 1048576, total * 1048576, i / 10, total / 10);
            System.Threading.Thread.Sleep(100);
            int status; d.GetOperationStatus(out status);
            if (status == 3 || status == 4) break;  // PDOPS_CANCELLED / PDOPS_STOPPED
        }
        d.StopProgressDialog();
        Marshal.ReleaseComObject(d);
    }
}
"@
Add-Type -TypeDefinition $code
[FtrProgress]::Run($Action, $Seconds)
