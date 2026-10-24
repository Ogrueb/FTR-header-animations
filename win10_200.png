// SPDX-License-Identifier: AGPL-3.0-or-later
// show_progress_dialog.cs - same as show_progress_dialog.ps1, for systems without PowerShell (Vista).
// C# 2.0, so it compiles with the .NET 2.0 compiler that ships with Vista and Windows 7:
//
//   C:\Windows\Microsoft.NET\Framework\v2.0.50727\csc.exe /nologo /out:show_progress_dialog.exe show_progress_dialog.cs
//   show_progress_dialog.exe 2 40        (action 2 = copying -> FTR 201, for 40 seconds)
//
// Action = SPACTION: 0 none/processing->200, 1 moving->202, 2 copying->201, 3 recycling->204,
// 4 applying properties->203, 5 downloading->200, 10 deleting->205 (full list in the .ps1 header).
// Written 6 Oct 2026; the .ps1 version is tested on Win7, this one is not yet tested.
using System;
using System.Runtime.InteropServices;
using System.Threading;

[ComImport, Guid("0C9FB851-E5C9-43EB-A370-F0677B13874C"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IOperationsProgressDialog {
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

static class ShowProgressDialog {
    [STAThread]
    static int Main(string[] args) {
        int action = args.Length > 0 ? int.Parse(args[0]) : 5;
        int seconds = args.Length > 1 ? int.Parse(args[1]) : 40;
        string step = "CreateInstance";
        try {
            Type t = Type.GetTypeFromCLSID(new Guid("F8383852-FCD3-11D1-A6B9-006097DF5BD4")); // CLSID_ProgressDialog
            IOperationsProgressDialog d = (IOperationsProgressDialog)Activator.CreateInstance(t);
            // Win7 shell32 returns E_UNEXPECTED from SetOperation until StartProgressDialog has run.
            step = "StartProgressDialog"; d.StartProgressDialog(IntPtr.Zero, 0);
            step = "SetOperation";        d.SetOperation(action);
            step = "SetMode";             d.SetMode(1);                     // PDM_RUN
            step = "UpdateProgress";
            ulong total = (ulong)seconds * 10;
            for (ulong i = 0; i < total; i++) {
                d.UpdateProgress(i, total, i * 1048576, total * 1048576, i / 10, total / 10);
                Thread.Sleep(100);
                int status; d.GetOperationStatus(out status);
                if (status == 3 || status == 4) break;                      // cancelled / stopped
            }
            step = "StopProgressDialog"; d.StopProgressDialog();
            Marshal.ReleaseComObject(d);
            return 0;
        } catch (Exception e) {
            Console.Error.WriteLine(step + " failed: " + e.Message);
            return 1;
        }
    }
}
