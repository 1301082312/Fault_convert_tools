@echo off
rem Local example: point the regression test at your own reference data (not part of the tool).
rem Copy this file, edit the paths, and run it from anywhere.
cd /d "%~dp0\.."
set FCT_SAMPLE=D:\data\sample_A
set FCT_REF_SEISMIC_SGY=D:\data\sample_A_seismic.sgy
set FCT_REF_OVERLAY_SGY=D:\data\sample_A_overlay_p05.sgy
set FCT_TS_A=D:\data\segment_A_ts
set FCT_REF_BINARY_A=D:\data\segment_A_fault.npy
set FCT_ORIGIN_A=233,150,461
set FCT_REF_INSTANCE=D:\data\stitched\fault_instance.npy
set FCT_INSTANCE_ORIGIN=8,150,461
set FCT_START_A=136
set FCT_TS_B=D:\data\segment_B_ts
set FCT_START_B=121
set FCT_INLINES_B=220,232
python tests\test_against_x15.py %*
pause
