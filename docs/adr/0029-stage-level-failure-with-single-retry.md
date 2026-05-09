# Stage-Level Failure With Single Retry

The MVP will fail Analysis Runs at the Run Stage boundary: if a stage throws or returns invalid structured output, the system may retry that stage once and then mark the stage and run failed if it still does not recover. Previously persisted Pipeline Stage Outputs remain inspectable for debugging, evaluation, and the status page.

Warning-level issues such as Uncited Claims do not trigger retries or fail the run. They are recorded as Warning Codes and evaluation metrics.
