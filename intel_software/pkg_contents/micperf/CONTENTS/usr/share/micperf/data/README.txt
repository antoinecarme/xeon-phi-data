================================================================================
Intel(R) Xeon Phi(TM) Processor Performance Workloads: micp
Pickle Files Directory
================================================================================

Disclaimer and Legal Information:

You may not use or facilitate the use of this document in connection with
any infringement or other legal analysis concerning Intel products described
herein. You agree to grant Intel a non-exclusive, royalty-free license to
any patent claim thereafter drafted which includes subject matter disclosed
herein.

No license (express or implied, by estoppel or otherwise) to any intellectual
property rights is granted by this document.
All information provided here is subject to change without notice. Contact your
Intel representative to obtain the latest Intel product specifications and
roadmaps. The products described may contain design defects or errors known as
errata which may cause the product to deviate from published specifications.
Current characterized errata are available on request.

Copies of documents which have an order number and are referenced in this
document may be obtained by calling 1-800-548-4725 or by visiting:
http://www.intel.com/design/literature.htm (http://www.intel.com/design/literature.htm)
Intel technologies' features and benefits depend on system configuration and
may require enabled hardware, software or service activation. Learn more at
http://www.intel.com/ (http://www.intel.com/) or from the OEM or retailer.
No computer system can be absolutely secure.
Intel, Xeon, Xeon Phi and the Intel logo are trademarks of Intel Corporation
in the U.S. and/or other countries.

*Other names and brands may be claimed as the property of others.

Copyright 2017, Intel Corporation, All Rights Reserved.

================================================================================
Pickle File Directory
================================================================================

The pickle files in this directory are available for micprun when run with
the "-R" argument. The pickle files included in this distribution represent
the measurements run on Intel's reference systems.

These reference files were generated with the command line option "-k sgemm:dgemm:stream:hplinpack:linpack:hpcg". 
Here, the hpcg requires MPI to be installed where, MPI is part of the Intel(R) Parallel Studio XE Professional Edition.

Note : MPI runtimes are freely available. For further details, please refer to the INSTALL.txt and README.txt files
in /usr/share/doc/micperf-VERSION (RHEL) or /usr/share/doc/packages/micperf/ (SUSE).

Use micpinfo to determine the information about the system on which the pickle was created.
For example,
To print the kernel command line for each of the pickle files in the bash shell, use the following command with the directory
containing this README as the current working directory:

    $ for file in *.pkl; do echo $file; micpinfo --app '/proc/cmdline' $file ; done

Note:
  o The naming convention for the pickle files is:

        micp_run_stats_TAG.pkl

    where TAG is:

        memoryused_sku_osversion_micperfversion_offloadmethod_paramcategory

    example:

    micp_run_stats_mcdram_7250_SuSE-12_micperf-1.5.0_local_scaling.pkl

    Important:
    - memoryused refers to the kind of memory the workloads can explicitly allocate, values are: 'mcdram' and 'ddr'.
      'ddr' means that MCDRAM cannot be allocated explictly but it doesn't mean it won't be used. For instance, in the 
      Cache memory mode 'MCDRAM' is used as a cache for DDR memory. Thus, workloads will use MCDRAM.
      'mcdram' is used when MCDRAM can be allocated explicitly, when the processor is in the Flat or Hybrid memory mode.
      However, in this memory mode if the -D option is passed to micprun, MCDRAM use will be disabled. Which will cause
      the 'ddr' tag to be used.

    - offloadmethod for the Intel(R) Xeon Phi(TM) Processors X200 family offload method is always 'local'.
