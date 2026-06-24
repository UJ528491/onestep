from typing import get_type_hints


def test_workflow_constructors_depend_on_interfaces() -> None:
    from doc_auto.services.document_cleanup_workflow import DocumentCleanupWorkflow
    from doc_auto.services.interfaces import InputPreparer
    from doc_auto.services.pdf_workflow import PdfConversionWorkflow
    from doc_auto.services.resize_workflow import ResizeOnlyWorkflow

    cleanup_hints = get_type_hints(DocumentCleanupWorkflow.__init__)
    pdf_hints = get_type_hints(PdfConversionWorkflow.__init__)
    resize_hints = get_type_hints(ResizeOnlyWorkflow.__init__)

    assert cleanup_hints["input_pipeline"] is InputPreparer
    assert pdf_hints["input_pipeline"] is InputPreparer
    assert resize_hints["input_pipeline"] is InputPreparer
