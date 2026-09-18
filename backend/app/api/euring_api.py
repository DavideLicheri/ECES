"""
EURING API Endpoints
REST API for EURING code recognition and conversion
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import asyncio
from datetime import datetime

from ..services.recognition_engine import RecognitionEngineImpl
from ..services.conversion_service import EuringConversionService
from ..services.semantic_converter import SemanticConverter
from ..services.skos_manager import SKOSManagerImpl
from ..services.domain_evolution_analyzer import DomainEvolutionAnalyzer
from ..services.semantic_field_grouper import SemanticFieldGrouper
from ..services.domain_compatibility_assessor import DomainCompatibilityAssessor
from ..services.semantic_domain_mapper import semantic_domain_mapper
from ..services.lookup_table_service import LookupTableService
from ..models.euring_models import SemanticDomain
from ..auth.dependencies import (
    get_current_active_user,
    require_matrix_edit_permission,
    get_current_user_optional
)
from ..auth.rate_limit import enforce_lizzy_rate_limit
from ..auth.models import User
from ..services.usage_logger import usage_logger
from ..services.field_translator import field_translator
from ..services.archive_service import archive_service
from ..services.database_service import database_service

# Initialize services
recognition_engine = RecognitionEngineImpl()
conversion_service = EuringConversionService()
semantic_converter = SemanticConverter()
skos_manager = SKOSManagerImpl()
domain_evolution_analyzer = DomainEvolutionAnalyzer()
semantic_field_grouper = SemanticFieldGrouper()
domain_compatibility_assessor = DomainCompatibilityAssessor()
lookup_table_service = LookupTableService()

# Bug trovato con Davide il 09-10/08/2026: le chiamate a asyncio.create_task()
# per l'archiviazione/logging in background non salvavano mai il riferimento
# al task. Il loop asyncio tiene solo un riferimento debole -- senza un
# riferimento forte altrove, il garbage collector puo' distruggere il task
# PRIMA che finisca, in qualunque momento (comportamento noto e documentato
# di asyncio). Sospettato essere la causa per cui la notifica generica di
# "alias toccato" (_maybe_notify_alias_touch, verso la fine di
# archive_string()) non produceva mai un log durante il test end-to-end del
# redesign condivisione, pur avendo scritto correttamente su database (i
# passaggi piu' veloci, all'inizio della funzione, completavano comunque).
# Fix standard raccomandato dalla documentazione Python: tenere i task in un
# insieme a livello di modulo, rimosso via callback al termine.
_background_tasks: set = set()


def _spawn_background(coro):
    """Avvia una coroutine in background tenendo un riferimento forte al
    task finche' non e' completa, per evitare che il garbage collector la
    interrompa a meta' (vedi nota sopra)."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# Create router
router = APIRouter(prefix="/api/euring", tags=["EURING"])


# Request/Response Models
class EuringRecognitionRequest(BaseModel):
    """Request model for EURING recognition"""
    euring_string: str = Field(..., description="EURING code string to recognize")
    include_analysis: bool = Field(False, description="Include detailed analysis in response")


class EuringParseRequest(BaseModel):
    """Request model for EURING string parsing"""
    euring_string: str = Field(..., description="EURING code string to parse")
    language: str = Field('it', description="Language for field names and values ('it' or 'en')")


class EuringBatchParseRequest(BaseModel):
    """Request model for batch EURING string parsing"""
    euring_strings: List[str] = Field(..., description="List of EURING code strings to parse")
    language: str = Field('it', description="Language for field names and values ('it' or 'en')")


class EuringParseResponse(BaseModel):
    """Response model for EURING string parsing"""
    success: bool
    euring_string: str
    detected_version: Optional[str] = None
    confidence: float = 0.0
    parsed_fields: Dict[str, Any] = Field(default_factory=dict)
    epe_compatible: bool = False
    field_count: int = 0
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


class EuringBatchParseResponse(BaseModel):
    """Response model for batch EURING string parsing"""
    success: bool
    total_strings: int
    successful_parses: int
    failed_parses: int
    results: List[Dict[str, Any]] = Field(default_factory=list)
    version_distribution: Dict[str, int] = Field(default_factory=dict)
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


class EuringRecognitionRequest(BaseModel):
    """Request model for EURING recognition"""
    euring_string: str = Field(..., description="EURING code string to recognize")
    include_analysis: bool = Field(False, description="Include detailed analysis in response")


class EuringRecognitionResponse(BaseModel):
    """Response model for EURING recognition"""
    success: bool
    version: Optional[str] = None
    confidence: Optional[float] = None
    euring_string: str
    length: int
    discriminant_analysis: Optional[Dict[str, Any]] = None
    detailed_analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class EuringConversionRequest(BaseModel):
    """Request model for EURING conversion"""
    euring_string: str = Field(..., description="EURING code string to convert")
    source_version: str = Field(..., description="Source version (1966, 1979, 2000, 2020)")
    target_version: str = Field(..., description="Target version (1966, 1979, 2000, 2020)")
    use_semantic: bool = Field(True, description="Use semantic conversion method")


class EuringConversionResponse(BaseModel):
    """Response model for EURING conversion"""
    success: bool
    converted_string: Optional[str] = None
    source_version: str
    target_version: str
    conversion_method: Optional[str] = None
    conversion_notes: List[str] = []
    semantic_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class BatchRecognitionRequest(BaseModel):
    """Request model for batch EURING recognition"""
    euring_strings: List[str] = Field(..., description="List of EURING code strings")
    include_analysis: bool = Field(False, description="Include detailed analysis")
    max_concurrent: int = Field(10, description="Maximum concurrent processing")


class BatchRecognitionResponse(BaseModel):
    """Response model for batch EURING recognition"""
    success: bool
    total_processed: int
    results: List[EuringRecognitionResponse]
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


class BatchConversionRequest(BaseModel):
    """Request model for batch EURING conversion"""
    conversions: List[EuringConversionRequest] = Field(..., description="List of conversion requests")
    max_concurrent: int = Field(10, description="Maximum concurrent processing")


class BatchConversionResponse(BaseModel):
    """Response model for batch EURING conversion"""
    success: bool
    total_processed: int
    results: List[EuringConversionResponse]
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


# Domain Evolution Request/Response Models
class DomainEvolutionResponse(BaseModel):
    """Response model for domain evolution"""
    success: bool
    domain: str
    evolution_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class DomainComparisonResponse(BaseModel):
    """Response model for domain comparison between versions"""
    success: bool
    domain: str
    version1: str
    version2: str
    comparison_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class DomainTimelineResponse(BaseModel):
    """Response model for domain evolution timeline"""
    success: bool
    timeline_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


# Matrix Editing Request/Response Models
class MatrixFieldUpdateRequest(BaseModel):
    """Request model for updating matrix field"""
    field_name: str = Field(..., description="Name of the field to update")
    version: str = Field(..., description="Version year (1966, 1979, 2000, 2020)")
    property: str = Field(..., description="Property to update (description, semantic_domain, data_type, length)")
    value: str = Field(..., description="New value for the property")
    notes: Optional[str] = Field(None, description="Optional notes about the change")


class MatrixFieldUpdateResponse(BaseModel):
    """Response model for matrix field update"""
    success: bool
    field_name: str
    version: str
    property: str
    old_value: Optional[str] = None
    new_value: str
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class MatrixBulkUpdateRequest(BaseModel):
    """Request model for bulk matrix updates"""
    updates: List[MatrixFieldUpdateRequest] = Field(..., description="List of field updates")


class MatrixBulkUpdateResponse(BaseModel):
    """Response model for bulk matrix updates"""
    success: bool
    total_updates: int
    successful_updates: int
    failed_updates: int
    results: List[MatrixFieldUpdateResponse]
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class MatrixFieldAddRequest(BaseModel):
    """Request model for adding a new field to a version"""
    field_name: str = Field(..., description="Name of the field to add")
    version: str = Field(..., description="Version year (1966, 1979, 2000, 2020)")
    position: int = Field(..., description="Position in the format")
    data_type: str = Field(default="string", description="Data type of the field")
    length: int = Field(default=10, description="Length of the field")
    description: Optional[str] = Field(None, description="Description of the field")


class MatrixFieldDeleteRequest(BaseModel):
    """Request model for deleting a field from a version"""
    field_name: str = Field(..., description="Name of the field to delete")
    version: str = Field(..., description="Version year (1966, 1979, 2000, 2020)")


class LookupTableResponse(BaseModel):
    """Response model for field lookup table"""
    success: bool
    field_name: str
    version: str
    lookup_table: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class AllLookupTablesResponse(BaseModel):
    """Response model for all lookup tables in a version"""
    success: bool
    version: str
    lookup_tables: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    total_tables: int = 0
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class LookupTableUpdateRequest(BaseModel):
    """Request model for updating a lookup table"""
    field_name: str = Field(..., description="Name of the field")
    version: str = Field(..., description="Version year")
    lookup_data: Dict[str, Any] = Field(..., description="Lookup table data with values array")


# API Endpoints

@router.post("/recognize", response_model=EuringRecognitionResponse)
async def recognize_euring(
    request: EuringRecognitionRequest,
    # Uno dei 4 endpoint chiamati da Lizzy -- rate limit dedicato
    # sull'account 'lizzy' (priorita' #5, 05/09/2026), vedi rate_limit.py.
    current_user: Optional[User] = Depends(enforce_lizzy_rate_limit)
):
    """
    Recognize EURING code version
    
    Analyzes an EURING code string and determines its version with confidence score.
    """
    start_time = datetime.now()
    
    try:
        # Validate input
        if not request.euring_string or not request.euring_string.strip():
            raise HTTPException(status_code=400, detail="EURING string cannot be empty")
        
        # Perform recognition
        result = await recognition_engine.recognize_version(request.euring_string.strip())
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Prepare response from RecognitionResult object
        response = EuringRecognitionResponse(
            success=True,
            version=result.detected_version.id if result.detected_version else None,
            confidence=result.confidence,
            euring_string=request.euring_string.strip(),
            length=len(request.euring_string.strip()),
            discriminant_analysis=result.analysis_details.confidence_factors if result.analysis_details else None,
            processing_time_ms=processing_time
        )
        
        # Add detailed analysis if requested
        if request.include_analysis:
            response.detailed_analysis = {
                'processing_time_ms': result.analysis_details.processing_time_ms if result.analysis_details else processing_time,
                'algorithm_version': result.analysis_details.algorithm_version if result.analysis_details else '2.0',
                'field_matches': result.analysis_details.field_matches if result.analysis_details else {}
            }
        
        # Log usage analytics (if user is authenticated)
        if current_user:
            try:
                log_data = {
                    "status": "success",
                    "detected_version": response.version,
                    "confidence": response.confidence,
                    "processing_time_ms": processing_time
                }
                # Log asynchronously to avoid blocking the response
                _spawn_background(usage_logger.log_query(
                    user=current_user,
                    query_type="recognition",
                    input_string=request.euring_string.strip(),
                    result=log_data,
                    processing_time=int(processing_time)
                ))
                # Archiviazione asincrona nell'archivio canonico a faccette
                # (non blocca la risposta; se non si archivia non e' un errore,
                # vedi archive_service.py)
                if response.version:
                    _spawn_background(archive_service.archive_string(
                        request.euring_string.strip(),
                        response.version,
                        owner_username=current_user.username
                    ))
            except Exception as log_error:
                # Don't let logging errors affect the main response
                print(f"Logging error: {log_error}")

        return response
        
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log error analytics (if user is authenticated)
        if current_user:
            try:
                log_data = {
                    "status": "error",
                    "error": str(e),
                    "processing_time_ms": processing_time
                }
                _spawn_background(usage_logger.log_query(
                    user=current_user,
                    query_type="recognition",
                    input_string=request.euring_string if request.euring_string else "",
                    result=log_data,
                    processing_time=int(processing_time)
                ))
            except Exception as log_error:
                print(f"Logging error: {log_error}")
        
        return EuringRecognitionResponse(
            success=False,
            euring_string=request.euring_string,
            length=len(request.euring_string) if request.euring_string else 0,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.post("/convert", response_model=EuringConversionResponse)
async def convert_euring(
    request: EuringConversionRequest,
    # Uno dei 4 endpoint chiamati da Lizzy -- rate limit dedicato
    # sull'account 'lizzy' (priorita' #5, 05/09/2026), vedi rate_limit.py.
    current_user: Optional[User] = Depends(enforce_lizzy_rate_limit)
):
    """
    Convert EURING code between versions

    Converts an EURING code from one version to another using semantic mapping.
    """
    start_time = datetime.now()

    try:
        # Validate input
        if not request.euring_string or not request.euring_string.strip():
            raise HTTPException(status_code=400, detail="EURING string cannot be empty")

        valid_versions = ['1966', '1979', '2000', '2020']
        if request.source_version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid source version: {request.source_version}")

        if request.target_version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid target version: {request.target_version}")

        # Perform conversion
        if request.use_semantic:
            result = conversion_service.convert_semantic(
                request.euring_string.strip(),
                request.source_version,
                request.target_version
            )
        else:
            result = conversion_service.convert(
                request.euring_string.strip(),
                request.source_version,
                request.target_version
            )

        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000

        # Prepare response
        response = EuringConversionResponse(
            success=result.get('success', False),
            converted_string=result.get('converted_string'),
            source_version=request.source_version,
            target_version=request.target_version,
            conversion_method=result.get('conversion_method', 'semantic' if request.use_semantic else 'legacy'),
            conversion_notes=result.get('conversion_notes', []),
            semantic_data=result.get('semantic_data') if request.use_semantic else None,
            processing_time_ms=processing_time
        )

        if not result.get('success'):
            response.error = result.get('error', 'Conversion failed')

        # Log usage analytics + archiviazione (solo utenti autenticati, come /recognize;
        # /convert non loggava affatto prima di questa modifica)
        if current_user:
            try:
                log_data = {
                    "status": "success" if response.success else "error",
                    "detected_version": request.source_version,
                    "processing_time_ms": processing_time
                }
                _spawn_background(usage_logger.log_query(
                    user=current_user,
                    query_type="conversion",
                    input_string=request.euring_string.strip(),
                    result=log_data,
                    processing_time=int(processing_time)
                ))
                if response.success:
                    # Si archiviano sia la stringa sorgente sia quella convertita
                    # (sono due stringhe EURING distinte, ciascuna deduplicata/
                    # archiviata a se' se si normalizza correttamente a 2020)
                    _spawn_background(archive_service.archive_string(
                        request.euring_string.strip(),
                        f"euring_{request.source_version}",
                        owner_username=current_user.username
                    ))
                    if response.converted_string:
                        _spawn_background(archive_service.archive_string(
                            response.converted_string,
                            f"euring_{request.target_version}",
                            owner_username=current_user.username
                        ))
            except Exception as log_error:
                print(f"Logging error: {log_error}")

        return response

    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return EuringConversionResponse(
            success=False,
            source_version=request.source_version,
            target_version=request.target_version,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.post("/batch/recognize", response_model=BatchRecognitionResponse)
async def batch_recognize_euring(request: BatchRecognitionRequest):
    """
    Batch recognize multiple EURING codes
    
    Processes multiple EURING strings concurrently for version recognition.
    """
    start_time = datetime.now()
    
    try:
        # Validate input
        if not request.euring_strings:
            raise HTTPException(status_code=400, detail="EURING strings list cannot be empty")
        
        if len(request.euring_strings) > 1000:
            raise HTTPException(status_code=400, detail="Maximum 1000 strings per batch")
        
        # Process in batches with concurrency limit
        semaphore = asyncio.Semaphore(request.max_concurrent)
        
        async def process_single(euring_string: str) -> EuringRecognitionResponse:
            async with semaphore:
                single_request = EuringRecognitionRequest(
                    euring_string=euring_string,
                    include_analysis=request.include_analysis
                )
                return await recognize_euring(single_request)
        
        # Process all strings
        results = await asyncio.gather(
            *[process_single(s) for s in request.euring_strings],
            return_exceptions=True
        )
        
        # Handle exceptions in results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(EuringRecognitionResponse(
                    success=False,
                    euring_string=request.euring_strings[i],
                    length=len(request.euring_strings[i]),
                    error=str(result)
                ))
            else:
                processed_results.append(result)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return BatchRecognitionResponse(
            success=True,
            total_processed=len(processed_results),
            results=processed_results,
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return BatchRecognitionResponse(
            success=False,
            total_processed=0,
            results=[],
            processing_time_ms=processing_time,
            error=str(e)
        )


@router.post("/batch/convert", response_model=BatchConversionResponse)
async def batch_convert_euring(request: BatchConversionRequest):
    """
    Batch convert multiple EURING codes
    
    Processes multiple EURING conversion requests concurrently.
    """
    start_time = datetime.now()
    
    try:
        # Validate input
        if not request.conversions:
            raise HTTPException(status_code=400, detail="Conversions list cannot be empty")
        
        if len(request.conversions) > 1000:
            raise HTTPException(status_code=400, detail="Maximum 1000 conversions per batch")
        
        # Process in batches with concurrency limit
        semaphore = asyncio.Semaphore(request.max_concurrent)
        
        async def process_single(conversion_request: EuringConversionRequest) -> EuringConversionResponse:
            async with semaphore:
                return await convert_euring(conversion_request)
        
        # Process all conversions
        results = await asyncio.gather(
            *[process_single(req) for req in request.conversions],
            return_exceptions=True
        )
        
        # Handle exceptions in results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(EuringConversionResponse(
                    success=False,
                    source_version=request.conversions[i].source_version,
                    target_version=request.conversions[i].target_version,
                    error=str(result)
                ))
            else:
                processed_results.append(result)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return BatchConversionResponse(
            success=True,
            total_processed=len(processed_results),
            results=processed_results,
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return BatchConversionResponse(
            success=False,
            total_processed=0,
            results=[],
            processing_time_ms=processing_time,
            error=str(e)
        )


@router.get("/versions/matrix")
async def get_euring_versions_matrix():
    """
    Get comparative matrix of all EURING versions
    
    Returns a structured comparison showing field evolution across versions,
    with fields aligned to EURING 2000 as reference.
    
    Requirements: New functionality for EURING model overview
    """
    start_time = datetime.now()
    
    try:
        # Initialize services and force reload to get latest data
        await skos_manager.reload_version_model()
        
        # Get all versions
        versions = await skos_manager.get_all_versions()
        
        if not versions:
            raise HTTPException(status_code=500, detail="No EURING versions found")
        
        # Assign semantic domains to all fields if not already assigned
        for version in versions:
            version.field_definitions = semantic_domain_mapper.assign_domains_to_fields(version.field_definitions)
        
        # Remove duplicate 2020 versions - keep only the official one
        filtered_versions = []
        seen_years = set()
        
        for version in versions:
            if version.year == 2020:
                # Prefer the official version
                if 'official' in version.id.lower():
                    if 2020 not in seen_years:
                        filtered_versions.append(version)
                        seen_years.add(2020)
                elif 2020 not in seen_years:
                    filtered_versions.append(version)
                    seen_years.add(2020)
            else:
                filtered_versions.append(version)
                seen_years.add(version.year)
        
        # Sort versions by year
        sorted_versions = sorted(filtered_versions, key=lambda v: v.year)
        
        # Build field matrix using EURING 2000 as reference (EPE order)
        reference_version = None
        for version in sorted_versions:
            if version.year == 2000:
                reference_version = version
                break
        
        if not reference_version:
            raise HTTPException(status_code=500, detail="Reference version (2000) not found")
        
        # Define EPE field order for EURING 2000 (from EPE ASP)
        epe_field_order = [
            'scheme', 'primary_identification_method', 'identification_number',
            'verification_metal_ring', 'metal_ring_information', 'other_marks',
            'species_reported', 'species_concluded', 'manipulation', 'moved_before',
            'catching_method', 'lures_used', 'sex_reported', 'sex_concluded',
            'age_reported', 'age_concluded', 'status', 'brood_size', 'pullus_age',
            'accuracy_pullus_age', 'day', 'month', 'year', 'accuracy_date', 'time',
            'area_code_edb', 'latitude', 'longitude', 'accuracy_coordinates',
            'condition_code', 'circumstances_code', 'circumstances_presumed',
            'euring_code_identifier', 'distance', 'direction', 'elapsed_time'
        ]
        
        # Mapping from EPE field names to JSON field names (semantic matching)
        epe_to_semantic_mapping = {
            'scheme': 'Ringing scheme identifier',
            'primary_identification_method': 'Primary identification method',
            'identification_number': 'Ring number',
            'verification_metal_ring': 'Metal ring verification',
            'metal_ring_information': 'Metal ring information',
            'other_marks': 'Other marks information',
            'species_reported': 'Species reported',
            'species_concluded': 'Species concluded',
            'manipulation': 'Manipulation code',
            'moved_before': 'Moved before capture',
            'catching_method': 'Catching method',
            'lures_used': 'Lures used',
            'sex_reported': 'Sex reported',
            'sex_concluded': 'Sex concluded',
            'age_reported': 'Age reported',
            'age_concluded': 'Age concluded',
            'status': 'Status code',
            'brood_size': 'Brood size',
            'pullus_age': 'Pullus age',
            'accuracy_pullus_age': 'Pullus age accuracy',
            'day': 'Day',
            'month': 'Month',
            'year': 'Year',
            'accuracy_date': 'Date accuracy',
            'time': 'Time',
            'area_code_edb': 'Area code',
            'latitude': 'Latitude',
            'longitude': 'Longitude',
            'accuracy_coordinates': 'Coordinate accuracy',
            'condition_code': 'Condition code',
            'circumstances_code': 'Circumstances code',
            'circumstances_presumed': 'Circumstances presumed',
            'euring_code_identifier': 'EURING code identifier',
            'distance': 'Distance',
            'direction': 'Direction',
            'elapsed_time': 'Elapsed time'
        }
        
        # Create field mapping matrix using EPE order
        field_matrix = []
        
        # Use EPE field order as the base structure
        for epe_field_name in epe_field_order:
            # Find the corresponding field in EURING 2000 by semantic meaning
            ref_field = None
            expected_semantic = epe_to_semantic_mapping.get(epe_field_name)
            
            for field in reference_version.field_definitions:
                if (field.semantic_meaning == expected_semantic or
                    field.name == epe_field_name or
                    field.name == epe_field_name.replace('_', ' ')):
                    ref_field = field
                    break
            
            if not ref_field:
                # Create a placeholder field based on EPE definition
                ref_field_name = epe_field_name
                ref_description = expected_semantic or epe_field_name.replace('_', ' ').title()
                ref_semantic = expected_semantic or epe_field_name
            else:
                ref_field_name = ref_field.name
                ref_description = ref_field.description
                ref_semantic = ref_field.semantic_meaning
            
            field_row = {
                "field_name": ref_field_name,
                "description": ref_description,
                "semantic_meaning": ref_semantic,
                "canonical_name": ref_field.canonical_name if ref_field else None,
                "epe_order": epe_field_order.index(epe_field_name) + 1,
                "versions": {}
            }
            
            # For each version, find corresponding field
            for version in sorted_versions:
                version_key = str(version.year)
                field_info = None
                
                # Try to find matching field by semantic meaning first, then by name
                expected_semantic = epe_to_semantic_mapping.get(epe_field_name)
                
                for field in version.field_definitions:
                    # Primary match: exact semantic meaning (guard against None matching any field)
                    if (field.semantic_meaning == expected_semantic or
                        (ref_semantic is not None and field.semantic_meaning == ref_semantic)):
                        field_info = {
                            "position": field.position,
                            "name": field.name,
                            "canonical_name": field.canonical_name,
                            "data_type": field.data_type,
                            "length": field.length,
                            "description": field.description,
                            "valid_values": field.valid_values if field.valid_values else [],
                            "valid_values_count": len(field.valid_values) if field.valid_values else 0,
                            "semantic_domain": field.semantic_domain.value if field.semantic_domain else None
                        }
                        break
                    # Secondary match: field name
                    elif (field.name == epe_field_name or field.name == ref_field_name or
                          field.name == epe_field_name.replace('_', ' ')):
                        field_info = {
                            "position": field.position,
                            "name": field.name,
                            "canonical_name": field.canonical_name,
                            "data_type": field.data_type,
                            "length": field.length,
                            "description": field.description,
                            "valid_values": field.valid_values if field.valid_values else [],
                            "valid_values_count": len(field.valid_values) if field.valid_values else 0,
                            "semantic_domain": field.semantic_domain.value if field.semantic_domain else None
                        }
                        break
                    # Tertiary match: special cases for scheme-related fields
                    elif (epe_field_name == 'scheme' and
                          ('scheme' in field.name.lower() or 'scheme' in (field.semantic_meaning or '').lower())):
                        field_info = {
                            "position": field.position,
                            "name": field.name,
                            "canonical_name": field.canonical_name,
                            "data_type": field.data_type,
                            "length": field.length,
                            "description": field.description,
                            "valid_values": field.valid_values if field.valid_values else [],
                            "valid_values_count": len(field.valid_values) if field.valid_values else 0,
                            "semantic_domain": field.semantic_domain.value if field.semantic_domain else None
                        }
                        break
                
                field_row["versions"][version_key] = field_info
            
            field_matrix.append(field_row)
        
        # Add any additional fields that exist in versions but are not in EPE order
        all_field_names_in_matrix = {field_row["field_name"] for field_row in field_matrix}
        
        print(f"🔍 [Matrix] Fields in EPE order: {len(all_field_names_in_matrix)}")
        print(f"🔍 [Matrix] Checking for additional fields in {len(sorted_versions)} versions...")
        
        additional_fields_count = 0
        for version in sorted_versions:
            for field in version.field_definitions:
                if field.name not in all_field_names_in_matrix:
                    # This field exists in a version but wasn't included in EPE order
                    print(f"➕ [Matrix] Found additional field: {field.name} in version {version.year} at position {field.position}")
                    
                    additional_field_row = {
                        "field_name": field.name,
                        "description": field.description,
                        "semantic_meaning": field.semantic_meaning,
                        "canonical_name": field.canonical_name,
                        "epe_order": 999,  # Put additional fields at the end
                        "versions": {}
                    }
                    
                    # Check all versions for this field
                    for check_version in sorted_versions:
                        check_version_key = str(check_version.year)
                        field_info = None
                        
                        for check_field in check_version.field_definitions:
                            if check_field.name == field.name:
                                field_info = {
                                    "position": check_field.position,
                                    "name": check_field.name,
                                    "canonical_name": check_field.canonical_name,
                                    "data_type": check_field.data_type,
                                    "length": check_field.length,
                                    "description": check_field.description,
                                    "valid_values": check_field.valid_values if check_field.valid_values else [],
                                    "valid_values_count": len(check_field.valid_values) if check_field.valid_values else 0,
                                    "semantic_domain": check_field.semantic_domain.value if check_field.semantic_domain else None
                                }
                                break
                        
                        additional_field_row["versions"][check_version_key] = field_info
                    
                    field_matrix.append(additional_field_row)
                    all_field_names_in_matrix.add(field.name)
                    additional_fields_count += 1
        
        print(f"✅ [Matrix] Added {additional_fields_count} additional fields to matrix")
        print(f"✅ [Matrix] Total fields in matrix: {len(field_matrix)}")
        
        
        
        # Add version metadata
        version_metadata = []
        for version in sorted_versions:
            version_metadata.append({
                "year": version.year,
                "id": version.id,
                "name": version.name,
                "description": version.description,
                "total_fields": len(version.field_definitions)
            })
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return {
            "success": True,
            "versions_metadata": version_metadata,
            "field_matrix": field_matrix,
            "reference_version": reference_version.year,
            "total_fields": len(field_matrix),
            "processing_time_ms": processing_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return {
            "success": False,
            "error": str(e),
            "processing_time_ms": processing_time
        }


PIPE_DELIMITED_VERSIONS = {'1966', '2020'}  # versioni con separatore; il 1966 usa spazi, 2020 usa |

def _check_position_conflict(version_obj, field_name: str, new_pos: int, new_length: int) -> list:
    """Return list of field names that conflict with the given position/index.

    Per versioni pipe-delimited (2020+): position = indice campo (1-based),
    la lunghezza è solo metadato del contenuto → conflitto solo su indice duplicato.
    Per versioni fixed-width (1979, 2000): conflitto su overlap di range caratteri.
    """
    version_year = str(getattr(version_obj, 'year', ''))
    conflicts = []

    if version_year in ('2020',):
        # Pipe-delimited: controlla solo duplicato di indice
        for field in version_obj.field_definitions:
            if field.name == field_name:
                continue
            if field.position == new_pos:
                conflicts.append(field.name)
    else:
        # Fixed-width: controlla overlap di range caratteri
        new_range = set(range(new_pos, new_pos + new_length))
        for field in version_obj.field_definitions:
            if field.name == field_name:
                continue
            existing_range = set(range(field.position, field.position + field.length))
            if new_range & existing_range:
                conflicts.append(field.name)
    return conflicts


@router.put("/versions/matrix/field", response_model=MatrixFieldUpdateResponse)
async def update_matrix_field(
    request: MatrixFieldUpdateRequest,
    current_user: User = Depends(require_matrix_edit_permission)
):
    """
    Update a single field in the EURING matrix
    
    Allows editing of field properties like description, semantic domain, data type, etc.
    Changes are saved to the SKOS repository for persistence.
    
    Requirements: Matrix editing functionality for SKOS semantic definitions
    """
    start_time = datetime.now()
    
    try:
        # Validate input
        if not request.field_name or not request.field_name.strip():
            raise HTTPException(status_code=400, detail="Field name cannot be empty")

        valid_versions = ['1966', '1979', '2000', '2020']
        if request.version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version: {request.version}")

        valid_properties = ['name', 'description', 'semantic_domain', 'data_type', 'length', 'semantic_meaning', 'position', 'canonical_name']
        if request.property not in valid_properties:
            raise HTTPException(status_code=400, detail=f"Invalid property: {request.property}. Valid: {valid_properties}")
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Find the version
        version_id = f"euring_{request.version}"
        version = await skos_manager.get_version_by_id(version_id)
        
        if not version:
            raise HTTPException(status_code=404, detail=f"Version {request.version} not found")
        
        # Find the field using cross-version name resolution
        # (field names differ between versions, e.g. 'scheme_code' in 2000 vs 'scheme_country' in 1979)
        field_to_update = lookup_table_service._find_field_in_version(version, request.field_name)
        
        if not field_to_update:
            raise HTTPException(status_code=404, detail=f"Field '{request.field_name}' not found in version {request.version}")
        
        # Store old value for response
        old_value = getattr(field_to_update, request.property, None)
        if hasattr(old_value, 'value'):  # Handle enum values
            old_value = old_value.value
        
        # Update the field property
        if request.property == 'semantic_domain':
            from ..models.euring_models import SemanticDomain
            if not request.value or request.value.strip() == '':
                field_to_update.semantic_domain = None
            else:
                try:
                    semantic_domain = SemanticDomain(request.value.lower())
                    field_to_update.semantic_domain = semantic_domain
                except ValueError:
                    valid_domains = [d.value for d in SemanticDomain]
                    raise HTTPException(status_code=400, detail=f"Invalid semantic domain: {request.value}. Valid: {valid_domains}")
        
        elif request.property == 'length':
            try:
                new_length = int(request.value)
            except ValueError:
                raise HTTPException(status_code=400, detail="Length must be a valid integer")
            conflicts = _check_position_conflict(version, field_to_update.name, field_to_update.position, new_length)
            if conflicts:
                raise HTTPException(status_code=409, detail=f"Position conflict: changing length would overlap with fields: {conflicts}")
            field_to_update.length = new_length

        elif request.property == 'position':
            try:
                new_pos = int(request.value)
            except ValueError:
                raise HTTPException(status_code=400, detail="Position must be a valid integer")
            conflicts = _check_position_conflict(version, field_to_update.name, new_pos, field_to_update.length)
            if conflicts:
                raise HTTPException(status_code=409, detail=f"Position conflict: position {new_pos} would overlap with fields: {conflicts}")
            field_to_update.position = new_pos
        
        elif request.property in ['name', 'description', 'semantic_meaning', 'data_type', 'canonical_name']:
            print(f"🔄 [API] Setting {request.property} from '{getattr(field_to_update, request.property, None)}' to '{request.value}'")
            setattr(field_to_update, request.property, request.value if request.value else None)
            print(f"✅ [API] Field {request.field_name}.{request.property} is now: '{getattr(field_to_update, request.property)}'")

        # Add evolution notes if provided
        if request.notes:
            if not field_to_update.evolution_notes:
                field_to_update.evolution_notes = []
            field_to_update.evolution_notes.append(f"Manual edit: {request.notes}")
        
        # Save the updated version using SKOS manager
        print(f"💾 [API] Calling skos_manager.update_version for {version.id}")
        await skos_manager.update_version(version)
        print(f"✅ [API] Save complete!")
        
        # Verify the field was actually updated in the version object
        verify_field = None
        for field in version.field_definitions:
            if field.name == request.field_name:
                verify_field = field
                break
        if verify_field:
            print(f"✅ [API] Verification: {request.field_name}.{request.property} = '{getattr(verify_field, request.property)}'")
        else:
            print(f"⚠️ [API] Warning: Could not find field {request.field_name} for verification")
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return MatrixFieldUpdateResponse(
            success=True,
            field_name=request.field_name,
            version=request.version,
            property=request.property,
            old_value=str(old_value) if old_value is not None else None,
            new_value=request.value,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return MatrixFieldUpdateResponse(
            success=False,
            field_name=request.field_name,
            version=request.version,
            property=request.property,
            new_value=request.value,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.post("/versions/matrix/field/add", response_model=MatrixFieldUpdateResponse)
async def add_field_to_version(
    request: MatrixFieldAddRequest,
    current_user: User = Depends(require_matrix_edit_permission)
):
    """
    Add a new field to a specific EURING version
    
    Creates a new field in the specified version with the provided properties.
    The field is saved to the SKOS repository for persistence.
    
    Requirements: Add missing fields to versions for complete SKOS definitions
    """
    start_time = datetime.now()
    
    try:
        # Validate input
        if not request.field_name or not request.field_name.strip():
            raise HTTPException(status_code=400, detail="Field name cannot be empty")
        
        valid_versions = ['1966', '1979', '2000', '2020']
        if request.version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version: {request.version}")
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Find the version
        version_id = f"euring_{request.version}"
        version_obj = await skos_manager.get_version_by_id(version_id)
        
        if not version_obj:
            raise HTTPException(status_code=404, detail=f"Version {request.version} not found")
        
        # Check if field already exists
        existing_field = None
        for field in version_obj.field_definitions:
            if field.name == request.field_name:
                existing_field = field
                break
        
        if existing_field:
            raise HTTPException(status_code=400, detail=f"Field '{request.field_name}' already exists in version {request.version}")

        # Check for position conflicts
        conflicts = _check_position_conflict(version_obj, request.field_name, request.position, request.length)
        if conflicts:
            raise HTTPException(status_code=409, detail=f"Position conflict: positions {request.position}-{request.position + request.length - 1} overlap with fields: {conflicts}")

        # Create new field
        from ..models.euring_models import FieldDefinition
        new_field = FieldDefinition(
            position=request.position,
            name=request.field_name,
            data_type=request.data_type,
            length=request.length,
            description=request.description or f"Campo {request.field_name} aggiunto manualmente alla versione {request.version}",
            valid_values=[],
            semantic_domain=None,
            evolution_notes=[f"Field added manually on {datetime.now().isoformat()}"]
        )
        
        # Add field to version
        version_obj.field_definitions.append(new_field)
        
        print(f"📝 [Add Field] Field '{request.field_name}' added to version object in memory")
        print(f"📝 [Add Field] Total fields before save: {len(version_obj.field_definitions)}")
        print(f"📝 [Add Field] New field details: position={new_field.position}, name={new_field.name}, length={new_field.length}")
        
        # Save the updated version using SKOS manager
        await skos_manager.update_version(version_obj)
        
        print(f"💾 [Add Field] Save operation completed")
        
        # Force reload to ensure the field is visible immediately
        await skos_manager.reload_version_model()
        
        print(f"🔄 [Add Field] Reload completed")
        
        # Verify the field was added by reloading the version
        reloaded_version = await skos_manager.get_version_by_id(version_id)
        field_exists = any(f.name == request.field_name for f in reloaded_version.field_definitions)
        
        print(f"✅ [Add Field] Field '{request.field_name}' added to {version_id}")
        print(f"✅ [Add Field] Verification: field exists after reload = {field_exists}")
        print(f"✅ [Add Field] Total fields in version after reload: {len(reloaded_version.field_definitions)}")
        
        # List all field positions to verify
        positions = sorted([f.position for f in reloaded_version.field_definitions])
        print(f"📊 [Add Field] All field positions after reload: {positions}")
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return MatrixFieldUpdateResponse(
            success=True,
            field_name=request.field_name,
            version=request.version,
            property="field_added",
            old_value=None,
            new_value=f"Added at position {request.position} (verified: {field_exists})",
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return MatrixFieldUpdateResponse(
            success=False,
            field_name=request.field_name,
            version=request.version,
            property="field_added",
            new_value="",
            error=str(e),
            processing_time_ms=processing_time
        )


@router.delete("/versions/matrix/field/remove", response_model=MatrixFieldUpdateResponse)
async def delete_field_from_version(
    request: MatrixFieldDeleteRequest,
    current_user: User = Depends(require_matrix_edit_permission)
):
    """
    Remove a field from a specific EURING version.

    Deletes the field definition from the version and persists the change.
    """
    start_time = datetime.now()
    try:
        valid_versions = ['1966', '1979', '2000', '2020']
        if request.version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version: {request.version}")

        await skos_manager.load_version_model()
        version_id = f"euring_{request.version}"
        version_obj = await skos_manager.get_version_by_id(version_id)
        if not version_obj:
            raise HTTPException(status_code=404, detail=f"Version {request.version} not found")

        # Use cross-version name resolution (same as UPDATE endpoint)
        field_to_delete = lookup_table_service._find_field_in_version(version_obj, request.field_name)
        if not field_to_delete:
            raise HTTPException(status_code=404, detail=f"Field '{request.field_name}' not found in version {request.version}")

        version_obj.field_definitions = [
            f for f in version_obj.field_definitions if f.name != field_to_delete.name
        ]

        await skos_manager.update_version(version_obj)
        await skos_manager.reload_version_model()

        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return MatrixFieldUpdateResponse(
            success=True,
            field_name=request.field_name,
            version=request.version,
            property="field_removed",
            old_value=request.field_name,
            new_value="",
            processing_time_ms=processing_time
        )
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return MatrixFieldUpdateResponse(
            success=False,
            field_name=request.field_name,
            version=request.version,
            property="field_removed",
            new_value="",
            error=str(e),
            processing_time_ms=processing_time
        )


async def update_matrix_bulk(request: MatrixBulkUpdateRequest):
    """
    Update multiple fields in the EURING matrix in bulk
    
    Allows batch editing of multiple field properties for efficient bulk operations.
    All changes are saved atomically to the SKOS repository.
    
    Requirements: Bulk matrix editing functionality for SKOS semantic definitions
    """
    start_time = datetime.now()
    
    try:
        if not request.updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        if len(request.updates) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 updates per bulk request")
        
        # Initialize services
        await skos_manager.load_version_model()
        
        results = []
        successful_updates = 0
        failed_updates = 0
        
        # Process each update
        for update_request in request.updates:
            try:
                # Reuse the single update logic
                result = await update_matrix_field(update_request)
                results.append(result)
                
                if result.success:
                    successful_updates += 1
                else:
                    failed_updates += 1
                    
            except Exception as e:
                # Create failed result
                failed_result = MatrixFieldUpdateResponse(
                    success=False,
                    field_name=update_request.field_name,
                    version=update_request.version,
                    property=update_request.property,
                    new_value=update_request.value,
                    error=str(e)
                )
                results.append(failed_result)
                failed_updates += 1
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return MatrixBulkUpdateResponse(
            success=failed_updates == 0,
            total_updates=len(request.updates),
            successful_updates=successful_updates,
            failed_updates=failed_updates,
            results=results,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return MatrixBulkUpdateResponse(
            success=False,
            total_updates=len(request.updates) if request.updates else 0,
            successful_updates=0,
            failed_updates=len(request.updates) if request.updates else 0,
            results=[],
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/versions")
async def get_supported_versions():
    """
    Get comparative matrix of all EURING versions
    
    Returns a structured comparison showing field evolution across versions,
    with fields aligned to the most recent version (2020) as reference.
    
    Requirements: New functionality for EURING model overview
    """
    start_time = datetime.now()
    
    try:
        # Initialize services
        await skos_manager.load_version_model()
        
        # Get all versions
        versions = await skos_manager.get_all_versions()
        
        if not versions:
            raise HTTPException(status_code=500, detail="No EURING versions found")

        # Deduplicate versions per year, keeping the one with the most field definitions
        deduped: dict[int, any] = {}
        for v in versions:
            if v.year not in deduped or len(v.field_definitions) > len(deduped[v.year].field_definitions):
                deduped[v.year] = v
        sorted_versions = sorted(deduped.values(), key=lambda v: v.year)

        # Build field matrix using 2020 as reference
        reference_version = deduped.get(2020)

        if not reference_version:
            raise HTTPException(status_code=500, detail="Reference version (2020) not found")
        
        # Create field mapping matrix
        field_matrix = []
        
        # Use reference version fields as the base structure
        for ref_field in reference_version.field_definitions:
            field_row = {
                "field_name": ref_field.name,
                "description": ref_field.description,
                "semantic_meaning": ref_field.semantic_meaning,
                "versions": {}
            }
            
            # For each version, find corresponding field
            for version in sorted_versions:
                version_key = str(version.year)
                field_info = None
                
                # Try to find matching field by name first, then by semantic meaning
                for field in version.field_definitions:
                    if (field.name == ref_field.name or
                        (ref_field.semantic_meaning is not None and
                         field.semantic_meaning == ref_field.semantic_meaning)):
                        field_info = {
                            "position": field.position,
                            "name": field.name,
                            "data_type": field.data_type,
                            "length": field.length,
                            "description": field.description,
                            "valid_values": field.valid_values if field.valid_values else [],
                            "valid_values_count": len(field.valid_values) if field.valid_values else 0,
                            "valid_values_type": field.valid_values_type.value if field.valid_values_type else None,
                            "valid_values_descriptions": field.valid_values_descriptions,
                            "valid_values_source": field.valid_values_source,
                            "valid_values_lookup_tool": field.valid_values_lookup_tool,
                            "valid_values_range": field.valid_values_range
                        }
                        break

                field_row["versions"][version_key] = field_info
            
            field_matrix.append(field_row)
        
        # Add version metadata
        version_metadata = []
        for version in sorted_versions:
            version_metadata.append({
                "year": version.year,
                "id": version.id,
                "name": version.name,
                "description": version.description,
                "total_fields": len(version.field_definitions)
            })
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return {
            "success": True,
            "versions_metadata": version_metadata,
            "field_matrix": field_matrix,
            "reference_version": reference_version.year,
            "total_fields": len(field_matrix),
            "processing_time_ms": processing_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return {
            "success": False,
            "error": str(e),
            "processing_time_ms": processing_time
        }
    """
    Get list of supported EURING versions
    
    Returns information about all supported EURING code versions.
    """
    return {
        "supported_versions": [
            {
                "version": "1966",
                "name": "EURING Code 1966",
                "description": "First version - space-separated format with 11 fields",
                "format": "space_separated",
                "typical_length": 55,
                "example": "5320 TA12345 3 11022023 5215N 01325E 10 2 050 0115 0750"
            },
            {
                "version": "1979",
                "name": "EURING Code 1979",
                "description": "Fixed-length concatenated format with 78 characters",
                "format": "fixed_length",
                "typical_length": 78,
                "example": "05320ISA12345 099200501199505215215N01325E10321--0500115--075010--001090------"
            },
            {
                "version": "2000",
                "name": "EURING Code 2000",
                "description": "Complex fixed-length format with encoded fields",
                "format": "fixed_length_encoded",
                "typical_length": 96,
                "example": "IABA0SA...7285004ZZ1187011870H0ZUMM55U-----0105200600600IA13+452409+009033908200400000---00086"
            },
            {
                "version": "2020",
                "name": "EURING Code 2020",
                "description": "Modern pipe-delimited format with decimal coordinates",
                "format": "pipe_delimited",
                "typical_length": 91,
                "example": "05320|ISA12345|0|09920|3|2|20230521|1430|52.25412|-1.34521|1|10|01|0|0|135.5|19.5|4|2|0|0|2"
            }
        ],
        "conversion_matrix": {
            "1966": ["1979", "2000", "2020"],
            "1979": ["1966", "2000", "2020"],
            "2000": ["1966", "1979", "2020"],
            "2020": ["1966", "1979", "2000"]
        }
    }


@router.get("/field/{field_name}")
async def get_field_info(
    field_name: str,
    version: str = "2020",
    # Uno dei 4 endpoint chiamati da Lizzy -- rate limit dedicato
    # sull'account 'lizzy' (priorita' #5, 05/09/2026), vedi rate_limit.py.
    current_user=Depends(enforce_lizzy_rate_limit)
):
    """
    Get full semantic information for a single EURING field.

    Returns valid values, descriptions, range constraints, and source info
    so that AI tools can explain any field without hardcoded tables.
    """
    await skos_manager.load_version_model()
    versions = await skos_manager.get_all_versions()

    # Deduplicate: keep version with most fields per year
    deduped: dict[int, any] = {}
    for v in versions:
        if v.year not in deduped or len(v.field_definitions) > len(deduped[v.year].field_definitions):
            deduped[v.year] = v

    # Resolve version year
    try:
        year = int(version)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version: {version}. Use 1966, 1979, 2000 or 2020.")

    target = deduped.get(year)
    if not target:
        raise HTTPException(status_code=404, detail=f"Version {year} not found.")

    field_name_norm = field_name.strip().lower().replace("_", " ")
    found = None
    for f in target.field_definitions:
        if f.name.lower() == field_name_norm or (f.canonical_name or "").lower() == field_name_norm:
            found = f
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{field_name}' not found in EURING {year}. "
                   f"Available fields: {[f.name for f in target.field_definitions]}"
        )

    return {
        "field_name": found.name,
        "canonical_name": found.canonical_name,
        "version": f"euring_{year}",
        "position": found.position,
        "length": found.length,
        "data_type": found.data_type,
        "description": found.description,
        "semantic_domain": found.semantic_domain.value if found.semantic_domain else None,
        "semantic_meaning": found.semantic_meaning,
        "valid_values_type": found.valid_values_type.value if found.valid_values_type else None,
        "valid_values": found.valid_values or [],
        "valid_values_descriptions": found.valid_values_descriptions,
        "valid_values_source": found.valid_values_source,
        "valid_values_lookup_tool": found.valid_values_lookup_tool,
        "valid_values_range": found.valid_values_range,
    }


@router.get("/field/{field_name}/lookup")
async def lookup_field_code(
    field_name: str,
    code: str,
    version: str = "2020",
    # Uno dei 4 endpoint chiamati da Lizzy -- rate limit dedicato
    # sull'account 'lizzy' (priorita' #5, 05/09/2026), vedi rate_limit.py.
    current_user=Depends(enforce_lizzy_rate_limit),
):
    """
    Decode a single code for an EURING field.

    Returns only the description for the given code — much lighter than
    fetching the full field definition (avoids returning 2052 entries for
    place_code when only one is needed).
    """
    await skos_manager.load_version_model()
    versions = await skos_manager.get_all_versions()

    deduped: dict[int, any] = {}
    for v in versions:
        if v.year not in deduped or len(v.field_definitions) > len(deduped[v.year].field_definitions):
            deduped[v.year] = v

    try:
        year = int(version)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version: {version}. Use 1966, 1979, 2000 or 2020.")

    target = deduped.get(year)
    if not target:
        raise HTTPException(status_code=404, detail=f"Version {year} not found.")

    field_name_norm = field_name.strip().lower().replace("_", " ")
    found = None
    for f in target.field_definitions:
        if f.name.lower() == field_name_norm or (f.canonical_name or "").lower() == field_name_norm:
            found = f
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{field_name}' not found in EURING {year}.",
        )

    descriptions = found.valid_values_descriptions or {}
    valid_values = found.valid_values or []

    if code in descriptions:
        return {
            "field_name": found.name,
            "version": f"euring_{year}",
            "code": code,
            "description": descriptions[code],
            "found": True,
        }
    elif code in valid_values:
        return {
            "field_name": found.name,
            "version": f"euring_{year}",
            "code": code,
            "description": None,
            "found": True,
        }
    else:
        return {
            "field_name": found.name,
            "version": f"euring_{year}",
            "code": code,
            "description": None,
            "found": False,
        }


@router.get("/field/{field_name}/search")
async def search_field_values(
    field_name: str,
    q: str,
    version: str = "2020",
    current_user=Depends(get_current_user_optional),
):
    """
    Search valid values of an EURING field by text (case-insensitive).

    Searches both codes (keys) and descriptions (values) in
    valid_values_descriptions. Returns all matching entries.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' cannot be empty.")

    await skos_manager.load_version_model()
    versions = await skos_manager.get_all_versions()

    deduped: dict[int, any] = {}
    for v in versions:
        if v.year not in deduped or len(v.field_definitions) > len(deduped[v.year].field_definitions):
            deduped[v.year] = v

    try:
        year = int(version)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version: {version}. Use 1966, 1979, 2000 or 2020.")

    target = deduped.get(year)
    if not target:
        raise HTTPException(status_code=404, detail=f"Version {year} not found.")

    field_name_norm = field_name.strip().lower().replace("_", " ")
    found = None
    for f in target.field_definitions:
        if f.name.lower() == field_name_norm or (f.canonical_name or "").lower() == field_name_norm:
            found = f
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{field_name}' not found in EURING {year}.",
        )

    descriptions = found.valid_values_descriptions or {}
    q_lower = q.strip().lower()

    matches = [
        {"code": code, "description": desc}
        for code, desc in descriptions.items()
        if q_lower in code.lower() or q_lower in (desc or "").lower()
    ]

    return {
        "field_name": found.name,
        "version": f"euring_{year}",
        "query": q,
        "matches": matches,
        "total": len(matches),
    }


# ── Semantic Field Editor endpoints ───────────────────────────────────────────

class FieldSemanticUpdateRequest(BaseModel):
    valid_values_type: Optional[str] = None
    valid_values: Optional[List[str]] = None
    valid_values_descriptions: Optional[Dict[str, str]] = None
    valid_values_source: Optional[str] = None
    valid_values_lookup_tool: Optional[str] = None
    valid_values_range: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class FieldSyncRequest(BaseModel):
    direction: str  # 'matrix_to_json' | 'json_to_matrix'
    mode: str       # 'append' | 'update'
    version: str = "2020"


def _resolve_field(version_obj, field_name: str):
    """Find a field by name or canonical name (case-insensitive)."""
    norm = field_name.strip().lower().replace("_", " ")
    for f in version_obj.field_definitions:
        if f.name.lower() == norm or (f.canonical_name or "").lower() == norm:
            return f
    return None


def _resolve_version(versions_list, year: int):
    """Return the version with the most fields for the given year."""
    candidates = [v for v in versions_list if v.year == year]
    if not candidates:
        return None
    return max(candidates, key=lambda v: len(v.field_definitions))


@router.put("/field/{field_name}")
async def update_field_semantic(
    field_name: str,
    request: FieldSemanticUpdateRequest,
    version: str = "2020",
    current_user: User = Depends(require_matrix_edit_permission),
):
    """Update semantic data (valid_values, descriptions, range, etc.) for a field."""
    await skos_manager.load_version_model()
    versions = await skos_manager.get_all_versions()

    try:
        year = int(version)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version: {version}")

    target = _resolve_version(versions, year)
    if not target:
        raise HTTPException(status_code=404, detail=f"Version {year} not found")

    field = _resolve_field(target, field_name)
    if not field:
        raise HTTPException(status_code=404, detail=f"Field '{field_name}' not found in version {year}")

    if request.valid_values_type is not None:
        try:
            from ..models.euring_models import ValidValuesType
            field.valid_values_type = ValidValuesType(request.valid_values_type) if request.valid_values_type else None
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid valid_values_type: {request.valid_values_type}")

    if request.valid_values is not None:
        field.valid_values = request.valid_values or None

    if request.valid_values_descriptions is not None:
        field.valid_values_descriptions = request.valid_values_descriptions or None

    if request.valid_values_source is not None:
        field.valid_values_source = request.valid_values_source or None

    if request.valid_values_lookup_tool is not None:
        field.valid_values_lookup_tool = request.valid_values_lookup_tool or None

    if request.valid_values_range is not None:
        field.valid_values_range = request.valid_values_range or None

    if request.description is not None:
        field.description = request.description

    await skos_manager.update_version(target)

    return {
        "success": True,
        "field_name": field.name,
        "version": f"euring_{year}",
        "updated_at": datetime.now().isoformat() + "Z",
        "updated_by": current_user.username,
    }


@router.post("/field/{field_name}/sync")
async def sync_field_semantic(
    field_name: str,
    request: FieldSyncRequest,
    current_user: User = Depends(require_matrix_edit_permission),
):
    """Sync structural ↔ semantic data for a single field."""
    if request.direction not in ("matrix_to_json", "json_to_matrix"):
        raise HTTPException(status_code=400, detail="direction must be 'matrix_to_json' or 'json_to_matrix'")
    if request.mode not in ("append", "update"):
        raise HTTPException(status_code=400, detail="mode must be 'append' or 'update'")

    await skos_manager.load_version_model()
    versions = await skos_manager.get_all_versions()

    try:
        year = int(request.version)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version: {request.version}")

    target = _resolve_version(versions, year)
    if not target:
        raise HTTPException(status_code=404, detail=f"Version {year} not found")

    field = _resolve_field(target, field_name)
    if not field:
        raise HTTPException(status_code=404, detail=f"Field '{field_name}' not found in version {year}")

    changes: List[Dict[str, Any]] = []

    def maybe_set(attr: str, new_val, label: str):
        old_val = getattr(field, attr, None)
        if old_val is not None and request.mode == "append":
            return
        if old_val == new_val:
            return
        old_display = old_val.value if hasattr(old_val, "value") else old_val
        setattr(field, attr, new_val)
        new_display = new_val.value if hasattr(new_val, "value") else new_val
        changes.append({"field": label, "before": old_display, "after": new_display})

    if request.direction == "matrix_to_json":
        from ..models.euring_models import ValidValuesType
        # Derive valid_values_type hint from data_type
        numeric_types = {"integer", "float", "numeric"}
        if field.data_type and field.data_type.lower() in numeric_types:
            maybe_set("valid_values_type", ValidValuesType.FREE_NUMERIC, "valid_values_type")
        elif field.valid_values:
            maybe_set("valid_values_type", ValidValuesType.ENUMERATION, "valid_values_type")

        # Propagate length to valid_values_range if free_numeric
        vvt = field.valid_values_type
        vvt_val = vvt.value if hasattr(vvt, "value") else vvt
        if vvt_val == "free_numeric" and field.length:
            old_range = field.valid_values_range or {}
            if "max_length" not in old_range or request.mode == "update":
                new_range = dict(old_range)
                new_range["max_length"] = field.length
                old_display = field.valid_values_range
                field.valid_values_range = new_range
                changes.append({"field": "valid_values_range.max_length", "before": old_display, "after": new_range})

    else:  # json_to_matrix
        from ..models.euring_models import ValidValuesType
        vvt = field.valid_values_type
        vvt_val = vvt.value if hasattr(vvt, "value") else vvt

        # Align data_type with valid_values_type
        if vvt_val == "free_numeric":
            numeric_types = {"integer", "float", "numeric"}
            if field.data_type not in numeric_types:
                maybe_set("data_type", "integer", "data_type")
        elif vvt_val == "enumeration":
            if field.data_type not in ("string", "alphanumeric"):
                maybe_set("data_type", "string", "data_type")

    if changes:
        await skos_manager.update_version(target)

    return {
        "success": True,
        "field_name": field.name,
        "version": f"euring_{year}",
        "direction": request.direction,
        "mode": request.mode,
        "changes": changes,
        "updated_by": current_user.username,
    }


@router.post("/reload")
async def reload_euring_data(current_user: User = Depends(require_matrix_edit_permission)):
    """Hot-reload all EURING JSON files from disk without restarting ECES."""
    await skos_manager.reload_version_model()
    return {
        "success": True,
        "message": "EURING data reloaded from disk",
        "reloaded_at": datetime.now().isoformat() + "Z",
    }


# ── End of Semantic Field Editor endpoints ────────────────────────────────────


@router.post("/parse", response_model=EuringParseResponse)
async def parse_euring_string(
    request: EuringParseRequest,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Parse a single EURING string into field-value pairs

    Provides detailed field-by-field breakdown, with automatic version
    recognition and version-appropriate parsing:
      - euring_2020: Euring2020PositionParser (pipe-delimited, position/name
        from euring_2020.json -- see that module for why this replaced the
        EPE-compatible parser here, which used a different, incompatible
        fixed-width-no-separator layout)
      - euring_2000: Euring2000EpeCompatibleParser (fixed-width, EPE-proven)
      - euring_1979 / euring_1966: their own dedicated parsers (previously
        not wired up here -- this endpoint used to return hardcoded example
        data for these two versions)

    Requirements: New functionality for string parsing interface
    """
    start_time = datetime.now()

    try:
        euring_string = request.euring_string.strip()

        if not euring_string:
            raise HTTPException(status_code=400, detail="EURING string cannot be empty")

        # Initialize services
        await skos_manager.load_version_model()

        # Step 1: Recognize version
        recognition_result = await recognition_engine.recognize_version(euring_string)

        if not recognition_result or not recognition_result.detected_version:
            raise HTTPException(status_code=400, detail="Could not recognize EURING version")

        detected_version = recognition_result.detected_version.id
        confidence = recognition_result.confidence

        # Step 2: Parse using the parser appropriate for the detected version
        parsed_fields = {}
        epe_compatible = False
        is_clean = True  # significativo solo per euring_2020, vedi sotto

        if detected_version == "euring_2020":
            from ..services.parsers.euring_2020_position_parser import Euring2020PositionParser
            version_model_2020 = await skos_manager.get_version_by_id("euring_2020")
            if not version_model_2020:
                raise HTTPException(status_code=400, detail="Version euring_2020 not available for parsing")
            parser = Euring2020PositionParser(version_model_2020)
            parse_result = parser.parse(euring_string)
            is_clean = parse_result["is_clean"]
            parsed_fields = dict(parse_result["fields"])
            if not is_clean:
                # Non blocchiamo la risposta: si restituisce comunque il meglio
                # che si riesce a mappare, con un avviso esplicito. L'eventuale
                # archiviazione a faccette (separata) resta invece rigorosa:
                # solo i parsing puliti (64/64 campi) entrano nell'archivio.
                parsed_fields["_parsing_warning"] = (
                    f"{parse_result['field_count']}/{parse_result['expected_field_count']} "
                    f"campi trovati: {'; '.join(parse_result['errors'])}"
                )

        elif detected_version == "euring_2000":
            from ..services.parsers.euring_2000_epe_compatible_parser import Euring2000EpeCompatibleParser
            parser = Euring2000EpeCompatibleParser()
            try:
                parsed_fields = parser.to_dict(euring_string)
                epe_compatible = True
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"EURING 2000 parsing failed: {e}")

        elif detected_version == "euring_1979":
            from ..services.parsers.euring_1979_parser import Euring1979Parser
            parser = Euring1979Parser()
            try:
                parsed_fields = parser.to_dict(euring_string)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"EURING 1979 parsing failed: {e}")

        elif detected_version == "euring_1966":
            from ..services.parsers.euring_1966_parser import Euring1966Parser
            parser = Euring1966Parser()
            try:
                parsed_fields = parser.to_dict(euring_string)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"EURING 1966 parsing failed: {e}")

        else:
            raise HTTPException(status_code=400, detail=f"Version {detected_version} not supported for parsing")

        # Step 3: Apply field translation based on language parameter
        if request.language and request.language != 'it':
            parsed_fields = field_translator.translate_parsed_fields(parsed_fields, request.language)

        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000

        # Log usage analytics + archiviazione (solo utenti autenticati, come /recognize;
        # /parse non loggava affatto prima di questa modifica)
        if current_user:
            try:
                log_data = {
                    "status": "success",
                    "detected_version": detected_version,
                    "confidence": confidence,
                    "processing_time_ms": processing_time
                }
                _spawn_background(usage_logger.log_query(
                    user=current_user,
                    query_type="validation",
                    input_string=euring_string,
                    result=log_data,
                    processing_time=int(processing_time)
                ))
                _spawn_background(archive_service.archive_string(
                    euring_string, detected_version,
                    owner_username=current_user.username
                ))
            except Exception as log_error:
                print(f"Logging error: {log_error}")

        return EuringParseResponse(
            success=True,
            euring_string=euring_string,
            detected_version=detected_version,
            confidence=confidence,
            parsed_fields=parsed_fields,
            epe_compatible=epe_compatible,
            field_count=len([k for k in parsed_fields.keys() if not k.startswith('_')]),
            processing_time_ms=processing_time,
            error=None
        )

    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return EuringParseResponse(
            success=False,
            euring_string=request.euring_string,
            detected_version=None,
            confidence=0.0,
            parsed_fields={},
            epe_compatible=False,
            field_count=0,
            processing_time_ms=processing_time,
            error=str(e)
        )


# Campi usati per calcolare i conteggi a faccetta nella GUI di ricerca
# dell'archivio. Prima versione: elenco curato, non tutti i 64 campi --
# calcolare i conteggi per tutti i campi ad ogni richiesta sarebbe troppo
# costoso senza una vista materializzata dedicata (non ancora fatta).
# I conteggi sono calcolati sull'intero archivio, non ricalcolati in base
# ai filtri gia' attivi (semplificazione nota per questa prima versione).
ARCHIVE_FACET_FIELDS = [
    "ringing scheme",
    "species concluded",
    "sex concluded",
    "age concluded",
    "condition",
    "circumstances",
]


@router.get("/archive/search")
async def search_archive(
    request: Request, page: int = 1, page_size: int = 20,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Ricerca a faccette nell'archivio canonico EURING 2020 (euring_2020_canonical
    + euring_2020_field_values, popolati da /recognize, /convert, /parse per gli
    utenti autenticati -- vedi archive_service.py).

    Filtri: qualunque parametro di query diverso da page/page_size viene trattato
    come coppia field_name=field_value da euring_2020.json (es. ?sex+concluded=M).
    Un solo valore per campo in questa prima versione (AND tra campi diversi,
    non OR all'interno dello stesso campo).

    Visibilita' (HANDOFF.md, punti 6-11, corretto 30/07/2026 -- PRIMA di questa
    modifica l'endpoint ignorava del tutto owner_username/visibility e
    restituiva l'intero archivio a chiunque): utente anonimo vede solo i
    record pubblici; utente autenticato vede pubblici + propri + condivisi
    con lui.
    """
    reserved = {"page", "page_size"}
    filters = {
        key: value
        for key, value in request.query_params.items()
        if key not in reserved and value
    }
    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    try:
        result = await database_service.search_canonical_2020(
            filters, page, page_size, requesting_user=current_user
        )
        facets = await database_service.facet_counts_2020(
            ARCHIVE_FACET_FIELDS, filters, requesting_user=current_user
        )
        return {
            "success": True,
            "total": result["total"],
            "page": page,
            "page_size": page_size,
            "results": result["results"],
            "facets": facets,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nella ricerca dell'archivio: {e}")


@router.get("/archive/alias/{alias_id}/summary")
async def get_alias_summary(
    alias_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Riepilogo per un anello (alias_id): quanti eventi sono visibili per
    intero all'utente corrente vs quanti totali esistono per quell'alias --
    la differenza e' il numero da mostrare nel placeholder "N eventi non
    condivisi con te" (HANDOFF.md, punti 9-10). Nessun contenuto dei record
    nascosti viene esposto tramite `visible_events`/`total_count`.

    `life_history` (aggiunto 03/08/2026): la stessa lista di eventi, ma in
    ordine cronologico per data evento e con un segnaposto (anno, nazione,
    specie -- mai numero di anello o proprietario) al posto degli eventi
    nascosti, invece del semplice conteggio. Pensato per dare un assaggio
    utile della "storia di vita" dell'anello senza violare la privacy di
    chi non ha condiviso -- indipendente dal meccanismo di condivisione
    (si applica a qualunque evento non visibile, a prescindere dal motivo).

    Utente anonimo: requesting_username=None, quindi "visibili" = solo
    pubblici (stessa semantica di /archive/search).
    """
    try:
        visible = await database_service.get_visible_events_for_alias(
            alias_id, current_user
        )
        total = await database_service.count_all_events_for_alias(alias_id)
        life_history = await database_service.get_alias_life_history(
            alias_id, current_user
        )
        return {
            "success": True,
            "alias_id": alias_id,
            "visible_events": visible,
            "visible_count": len(visible),
            "total_count": total,
            "hidden_count": max(0, total - len(visible)),
            "life_history": life_history,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel riepilogo dell'alias: {e}")


@router.get("/lizzy/species-place-pentad-stats")
async def lizzy_species_place_pentad_stats(
    species_code: str, place_code: str, pentad: int
):
    """
    Consultazione dei contatori aggregati e anonimi per Lizzy (HANDOFF.md,
    punto 14a, migrazione 004): quante volte questa combinazione
    specie+luogo+pentade e' gia' stata osservata, e da quanti schemi di
    inanellamento distinti proviene il dato.

    Nessun giudizio di "raro"/"plausibile" qui -- solo i numeri grezzi (nessuna
    soglia fissa di "sufficienza" e' stata introdotta, decisione 30/07/2026:
    la dichiarazione di provenienza sostituisce una soglia arbitraria).
    Dato interamente anonimo e aggregato, nessun endpoint di autenticazione
    richiesto -- non contiene mai contenuto di record, utenti, o stringhe.
    """
    if not (1 <= pentad <= 73):
        raise HTTPException(status_code=400, detail="pentad deve essere tra 1 e 73")

    try:
        stats = await database_service.get_lizzy_species_place_pentad_stats(
            species_code=species_code.strip(),
            place_code=place_code.strip(),
            pentad=pentad,
        )
        return {
            "success": True,
            "species_code": species_code,
            "place_code": place_code,
            "pentad": pentad,
            **stats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nella consultazione dei contatori Lizzy: {e}")


# ============================================================================
# Condivisione mirata reciproca e visibilita' pubblica, per (alias,
# proprietario) -- redesign 07/08/2026, migrazione 005. Sostituisce il
# vecchio meccanismo "richiedi contatto" (contact_requests, migrazione 003):
# quello si e' rivelato di fatto irraggiungibile in scenari reali, perche'
# la condivisione automatica precedente scattava sempre prima che una
# richiesta potesse avere senso (vedi HANDOFF.md, indagine 03/08/2026).
#
# Tutti e tre gli endpoint sotto richiedono che l'utente corrente possieda
# GIA' un proprio record su alias_id (verificato server-side in
# database_service._owns_alias) -- solo un proprietario dello stesso anello
# puo' vedere chi sono gli altri proprietari o impostare scelte di
# condivisione/pubblicazione. Nessun endpoint per "estranei senza dati
# propri sull'alias": quel caso e' coperto solo dalla vista pubblica/
# mascherata (search_canonical_2020/facet_counts_2020/get_alias_life_history).
# ============================================================================

class AliasPublicUpdate(BaseModel):
    is_public: bool

class AliasSharingUpdate(BaseModel):
    to_username: str
    state: str  # 'offered' | 'declined'
    message: Optional[str] = None


@router.get("/archive/alias/{alias_id}/sharing-status")
async def get_alias_sharing_status(
    alias_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """
    Stato delle proprie scelte di condivisione per questo alias: il proprio
    flag "pubblico" e, per ciascun altro proprietario dello stesso alias, lo
    stato reciproco (la mia scelta verso di lui, la sua verso di me, se la
    reciprocita' e' gia' raggiunta). Popola la UI di gestione condivisione in
    ArchivePanel.
    """
    try:
        status = await database_service.get_my_sharing_status(alias_id, current_user.username)
        if status is None:
            raise HTTPException(
                status_code=403,
                detail="Non possiedi dati su questo anello, oppure errore nel recupero dello stato.",
            )
        return {"success": True, **status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel recupero dello stato di condivisione: {e}")


@router.put("/archive/alias/{alias_id}/public")
async def set_alias_public(
    alias_id: int,
    body: AliasPublicUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """
    Imposta se il PROPRIO dato su questo alias e' pubblico -- unilaterale,
    non richiede reciprocita', non coinvolge gli altri proprietari dello
    stesso alias.
    """
    try:
        ok = await database_service.set_alias_public(alias_id, current_user.username, body.is_public)
        if not ok:
            raise HTTPException(
                status_code=403,
                detail="Non possiedi dati su questo anello, oppure errore nel salvataggio.",
            )
        return {"success": True, "is_public": body.is_public}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nell'impostare la visibilita' pubblica: {e}")


@router.put("/archive/alias/{alias_id}/sharing")
async def set_alias_sharing(
    alias_id: int,
    body: AliasSharingUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """
    Imposta la propria scelta di condividere ('offered') o rifiutare
    ('declined') il PROPRIO dato su questo alias con to_username -- efficace
    solo se anche to_username fa la stessa scelta verso current_user
    (reciprocita'). Aggiornabile in qualunque momento, nessun lock: si puo'
    sempre cambiare idea richiamando questo stesso endpoint.
    """
    if body.state not in ("offered", "declined"):
        raise HTTPException(status_code=400, detail="state deve essere 'offered' o 'declined'")
    try:
        ok = await database_service.set_alias_sharing_intent(
            alias_id=alias_id,
            from_username=current_user.username,
            to_username=body.to_username,
            state=body.state,
            message=body.message,
        )
        if not ok:
            raise HTTPException(
                status_code=403,
                detail="Tu o l'altro utente non possedete dati su questo anello, oppure errore nel salvataggio.",
            )
        return {"success": True, "state": body.state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nell'impostare la condivisione: {e}")


@router.post("/parse/batch", response_model=EuringBatchParseResponse)
async def parse_euring_strings_batch(request: EuringBatchParseRequest):
    """
    Parse multiple EURING strings in batch
    
    Useful for processing uploaded files with multiple strings.
    Returns results for each string with navigation support.
    
    Requirements: Batch processing for string parsing interface
    """
    start_time = datetime.now()
    
    try:
        if not request.euring_strings:
            raise HTTPException(status_code=400, detail="No EURING strings provided")
        
        if len(request.euring_strings) > 1000:
            raise HTTPException(status_code=400, detail="Maximum 1000 strings per batch")
        
        # Initialize services
        await skos_manager.load_version_model()
        
        results = []
        version_counts = {}
        
        for i, euring_string in enumerate(request.euring_strings):
            try:
                # Create individual parse request with language parameter
                individual_request = EuringParseRequest(
                    euring_string=euring_string,
                    language=request.language
                )
                
                # Parse individual string (reuse the parse logic)
                result = await parse_euring_string(individual_request)
                
                # Convert to dict and ensure all required fields are present
                result_dict = result.dict()
                result_dict['index'] = i
                
                # Ensure euring_string is always present (fix for duplicate string validation error)
                if 'euring_string' not in result_dict or not result_dict['euring_string']:
                    result_dict['euring_string'] = euring_string
                
                results.append(result_dict)
                
                # Count versions
                if result.success and result.detected_version:
                    version_counts[result.detected_version] = version_counts.get(result.detected_version, 0) + 1
                
            except Exception as e:
                # Add failed result with all required fields
                results.append({
                    'index': i,
                    'success': False,
                    'euring_string': euring_string,  # Ensure this is always present
                    'error': str(e),
                    'detected_version': None,
                    'confidence': 0.0,
                    'parsed_fields': {},
                    'epe_compatible': False,
                    'field_count': 0,
                    'processing_time_ms': 0
                })
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Calculate summary statistics
        successful_parses = sum(1 for r in results if r['success'])
        failed_parses = len(results) - successful_parses
        
        return EuringBatchParseResponse(
            success=True,
            total_strings=len(request.euring_strings),
            successful_parses=successful_parses,
            failed_parses=failed_parses,
            results=results,
            version_distribution=version_counts,
            processing_time_ms=processing_time,
            error=None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return EuringBatchParseResponse(
            success=False,
            total_strings=len(request.euring_strings) if request.euring_strings else 0,
            successful_parses=0,
            failed_parses=0,
            results=[],
            version_distribution={},
            processing_time_ms=processing_time,
            error=str(e)
        )
async def get_domain_evolution(domain: str):
    """
    Get evolution data for a specific semantic domain
    
    Returns historical changes and evolution timeline for the specified domain
    across all EURING versions.
    
    Requirements: 8.1
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions and domain evolutions for the analyzer
        versions = await skos_manager.get_all_versions()
        domain_evolution_analyzer.load_versions(versions)
        
        try:
            domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
            domain_evolution_analyzer.load_domain_evolutions([domain_evolution])
        except ValueError:
            # Domain evolution not available, continue with basic analysis
            pass
        
        # Get domain evolution analysis
        evolution_data = await domain_evolution_analyzer.analyze_domain_evolution(semantic_domain)
        
        # Get domain evolution summary from SKOS manager
        evolution_summary = await skos_manager.get_domain_evolution_summary(semantic_domain)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Prepare response data
        response_data = {
            "domain": semantic_domain.value,
            "evolution_summary": evolution_summary,
            "evolution_entries": [
                {
                    "version": entry.version,
                    "year": entry.year,
                    "changes": [
                        {
                            "change_type": change.change_type.value,
                            "field_name": change.field_name,
                            "semantic_impact": change.semantic_impact,
                            "compatibility_impact": change.compatibility_impact.value,
                            "previous_value": change.previous_value,
                            "new_value": change.new_value
                        }
                        for change in entry.changes
                    ],
                    "fields_added": entry.fields_added or [],
                    "fields_removed": entry.fields_removed or [],
                    "fields_modified": entry.fields_modified or [],
                    "semantic_notes": entry.semantic_notes or [],
                    "format_changes": entry.format_changes or []
                }
                for entry in evolution_data.evolution_entries
            ],
            "compatibility_matrix": {
                "available": evolution_data.compatibility_matrix is not None,
                "compatibility_map": {
                    f"{from_ver}->{to_ver}": level.value if hasattr(level, 'value') else str(level)
                    for (from_ver, to_ver), level in evolution_data.compatibility_matrix.compatibility_map.items()
                } if evolution_data.compatibility_matrix else {}
            },
            "field_evolution_map": evolution_data.field_evolution_map or {}
        }
        
        return DomainEvolutionResponse(
            success=True,
            domain=semantic_domain.value,
            evolution_data=response_data,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainEvolutionResponse(
            success=False,
            domain=domain,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/domains/{domain}/compare/{version1}/{version2}", response_model=DomainComparisonResponse)
async def compare_domain_versions(domain: str, version1: str, version2: str):
    """
    Compare two versions within a specific semantic domain
    
    Analyzes differences between two EURING versions for the specified domain,
    including field changes, compatibility assessment, and semantic evolution.
    
    Requirements: 8.2
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Validate versions
        valid_versions = ['1966', '1979', '2000', '2020']
        if version1 not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version1: {version1}")
        if version2 not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version2: {version2}")
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions and domain evolutions for the analyzer
        versions = await skos_manager.get_all_versions()
        domain_evolution_analyzer.load_versions(versions)
        
        try:
            domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
            domain_evolution_analyzer.load_domain_evolutions([domain_evolution])
        except ValueError:
            # Domain evolution not available, continue with basic analysis
            pass
        
        # Perform domain comparison using the analyzer
        analyzer_comparison = await domain_evolution_analyzer.compare_domain_versions(
            semantic_domain, version1, version2
        )
        
        # Get additional comparison data from SKOS manager
        skos_comparison = await skos_manager.compare_domain_between_versions(
            semantic_domain, version1, version2
        )
        
        # Get domain-specific field mappings if available
        field_mappings = []
        try:
            field_mappings = await skos_manager.get_domain_field_mappings(
                semantic_domain, version1, version2
            )
        except ValueError:
            # Field mappings not available
            pass
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Combine comparison data
        comparison_data = {
            "domain": semantic_domain.value,
            "version1": version1,
            "version2": version2,
            "analyzer_comparison": analyzer_comparison,
            "skos_comparison": skos_comparison,
            "field_mappings": field_mappings,
            "summary": {
                "compatibility_level": analyzer_comparison.get("compatibility_level", "unknown"),
                "total_changes": analyzer_comparison.get("evolution_summary", {}).get("total_changes", 0),
                "fields_added": len(analyzer_comparison.get("field_comparison", {}).get("added", [])),
                "fields_removed": len(analyzer_comparison.get("field_comparison", {}).get("removed", [])),
                "fields_modified": len(analyzer_comparison.get("field_comparison", {}).get("modified", [])),
                "has_field_mappings": len(field_mappings) > 0
            }
        }
        
        return DomainComparisonResponse(
            success=True,
            domain=semantic_domain.value,
            version1=version1,
            version2=version2,
            comparison_data=comparison_data,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainComparisonResponse(
            success=False,
            domain=domain,
            version1=version1,
            version2=version2,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/domains/timeline", response_model=DomainTimelineResponse)
async def get_domains_timeline(
    domain: Optional[str] = None,
    include_details: bool = True
):
    """
    Get evolution timeline for domains
    
    Returns chronological evolution timeline for all domains or a specific domain,
    showing historical changes and development patterns over time.
    
    Requirements: 8.3
    """
    start_time = datetime.now()
    
    try:
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions and domain evolutions for the analyzer
        versions = await skos_manager.get_all_versions()
        domain_evolution_analyzer.load_versions(versions)
        
        # Load all available domain evolutions
        domain_evolutions = []
        for semantic_domain in SemanticDomain:
            try:
                domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
                domain_evolutions.append(domain_evolution)
            except ValueError:
                # Domain evolution not available, skip
                continue
        
        if domain_evolutions:
            domain_evolution_analyzer.load_domain_evolutions(domain_evolutions)
        
        timeline_data = {}
        
        if domain:
            # Get timeline for specific domain
            try:
                semantic_domain = SemanticDomain(domain.lower())
            except ValueError:
                valid_domains = [d.value for d in SemanticDomain]
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
                )
            
            # Generate timeline for specific domain
            domain_timeline = await domain_evolution_analyzer.generate_evolution_timeline(
                semantic_domain, include_details
            )
            
            timeline_data = {
                "type": "single_domain",
                "domain": semantic_domain.value,
                "timeline": domain_timeline
            }
        else:
            # Get timeline for all domains
            all_domain_timelines = {}
            
            for semantic_domain in SemanticDomain:
                try:
                    domain_timeline = await domain_evolution_analyzer.generate_evolution_timeline(
                        semantic_domain, include_details
                    )
                    all_domain_timelines[semantic_domain.value] = domain_timeline
                except Exception:
                    # Skip domains without evolution data
                    continue
            
            # Create combined timeline
            combined_timeline_events = []
            for domain_name, domain_timeline in all_domain_timelines.items():
                for event in domain_timeline.get("timeline_events", []):
                    combined_event = event.copy()
                    combined_event["domain"] = domain_name
                    combined_timeline_events.append(combined_event)
            
            # Sort combined events by year
            combined_timeline_events.sort(key=lambda e: e.get("year", 0))
            
            # Calculate overall statistics
            overall_stats = {
                "total_domains": len(all_domain_timelines),
                "total_versions": len(versions),
                "domains_with_evolution_data": len([d for d in all_domain_timelines.values() if d.get("timeline_events")]),
                "evolution_period": {
                    "start_year": min((d.get("evolution_period", {}).get("start_year", 9999) 
                                     for d in all_domain_timelines.values() 
                                     if d.get("evolution_period", {}).get("start_year")), default=None),
                    "end_year": max((d.get("evolution_period", {}).get("end_year", 0) 
                                   for d in all_domain_timelines.values() 
                                   if d.get("evolution_period", {}).get("end_year")), default=None)
                }
            }
            
            timeline_data = {
                "type": "all_domains",
                "domain_timelines": all_domain_timelines,
                "combined_timeline": combined_timeline_events,
                "overall_statistics": overall_stats
            }
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return DomainTimelineResponse(
            success=True,
            timeline_data=timeline_data,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainTimelineResponse(
            success=False,
            error=str(e),
            processing_time_ms=processing_time
        )


# Domain Analysis Request/Response Models
class DomainFieldsResponse(BaseModel):
    """Response model for domain field grouping"""
    success: bool
    domain: str
    field_groups: Optional[List[Dict[str, Any]]] = None
    semantic_analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class DomainCompatibilityResponse(BaseModel):
    """Response model for domain compatibility assessment"""
    success: bool
    domain: str
    from_version: str
    to_version: str
    compatibility_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class DomainExportResponse(BaseModel):
    """Response model for domain export"""
    success: bool
    domain: str
    export_data: Optional[Dict[str, Any]] = None
    export_format: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


@router.get("/domains/{domain}/fields", response_model=DomainFieldsResponse)
async def get_domain_fields(domain: str):
    """
    Get field grouping analysis for a specific semantic domain
    
    Analyzes and groups fields within a domain by semantic relationships,
    providing insights into field organization and semantic themes.
    
    Requirements: 8.4
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions for analysis
        versions = await skos_manager.get_all_versions()
        
        # Collect all fields for the domain across versions
        all_domain_fields = []
        for version in versions:
            domain_fields = [f for f in version.field_definitions if f.semantic_domain == semantic_domain]
            all_domain_fields.extend(domain_fields)
        
        # Perform semantic field grouping
        field_groups = semantic_field_grouper.group_fields_by_semantics(
            all_domain_fields, semantic_domain
        )
        
        # Perform domain-specific analysis
        domain_analysis = semantic_field_grouper.analyze_domain_specific_fields(
            semantic_domain, versions
        )
        
        # Categorize semantic fields
        field_categories = semantic_field_grouper.categorize_semantic_fields(
            all_domain_fields, semantic_domain
        )
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Prepare response data
        field_groups_data = [
            {
                "group_id": group.group_id,
                "group_name": group.group_name,
                "fields": group.fields,
                "semantic_theme": group.semantic_theme,
                "cohesion_score": group.cohesion_score,
                "relationships": [
                    {
                        "field1": rel.field1,
                        "field2": rel.field2,
                        "relationship_type": rel.relationship_type,
                        "strength": rel.strength,
                        "semantic_basis": rel.semantic_basis
                    }
                    for rel in group.relationships
                ]
            }
            for group in field_groups
        ]
        
        semantic_analysis_data = {
            "domain_analysis": domain_analysis,
            "field_categories": field_categories,
            "total_fields": len(all_domain_fields),
            "total_groups": len(field_groups),
            "versions_analyzed": len(versions),
            "grouping_statistics": {
                "average_group_size": sum(len(g.fields) for g in field_groups) / len(field_groups) if field_groups else 0,
                "average_cohesion": sum(g.cohesion_score for g in field_groups) / len(field_groups) if field_groups else 0,
                "ungrouped_fields": len(all_domain_fields) - sum(len(g.fields) for g in field_groups)
            }
        }
        
        return DomainFieldsResponse(
            success=True,
            domain=semantic_domain.value,
            field_groups=field_groups_data,
            semantic_analysis=semantic_analysis_data,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainFieldsResponse(
            success=False,
            domain=domain,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/domains/{domain}/compatibility/{fromVersion}/{toVersion}", response_model=DomainCompatibilityResponse)
async def get_domain_compatibility(domain: str, fromVersion: str, toVersion: str):
    """
    Get domain-specific compatibility assessment between two versions
    
    Analyzes conversion compatibility for a specific domain, including
    lossy conversion detection and detailed compatibility information.
    
    Requirements: 8.5
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Validate versions
        valid_versions = ['1966', '1979', '2000', '2020']
        if fromVersion not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid fromVersion: {fromVersion}")
        if toVersion not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid toVersion: {toVersion}")
        
        # Convert year versions to full version IDs
        full_from_version = f"euring_{fromVersion}"
        full_to_version = f"euring_{toVersion}"
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions and domain evolutions
        versions = await skos_manager.get_all_versions()
        domain_compatibility_assessor.load_versions(versions)
        
        # Load domain evolutions if available
        try:
            domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
            domain_compatibility_assessor.load_domain_evolutions([domain_evolution])
        except ValueError:
            # Domain evolution not available, continue with basic analysis
            pass
        
        # Perform compatibility assessment
        compatibility_result = await domain_compatibility_assessor.assess_domain_compatibility(
            semantic_domain, full_from_version, full_to_version, detailed_analysis=True
        )
        
        # Get additional compatibility matrix data
        try:
            compatibility_matrix = await domain_compatibility_assessor.create_domain_compatibility_matrix(
                semantic_domain, [full_from_version, full_to_version]
            )
            matrix_data = {
                "available": True,
                "compatibility_level": compatibility_matrix.get_compatibility(full_from_version, full_to_version).value
            }
        except Exception:
            matrix_data = {"available": False}
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Prepare comprehensive compatibility data
        compatibility_data = {
            "assessment_result": dict(compatibility_result),
            "compatibility_matrix": matrix_data,
            "summary": {
                "overall_compatibility": compatibility_result.compatibility_level,
                "is_lossy_conversion": compatibility_result.is_lossy,
                "total_warnings": len(compatibility_result.conversion_warnings),
                "field_compatibility_count": len(compatibility_result.field_compatibility),
                "loss_types": list(set(loss.get('type', 'unknown') for loss in compatibility_result.loss_details))
            },
            "detailed_analysis": {
                "field_level_compatibility": compatibility_result.field_compatibility,
                "conversion_warnings": compatibility_result.conversion_warnings,
                "conversion_notes": compatibility_result.conversion_notes,
                "loss_details": compatibility_result.loss_details
            }
        }
        
        return DomainCompatibilityResponse(
            success=True,
            domain=semantic_domain.value,
            from_version=fromVersion,
            to_version=toVersion,
            compatibility_data=compatibility_data,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainCompatibilityResponse(
            success=False,
            domain=domain,
            from_version=fromVersion,
            to_version=toVersion,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/domains/export/{domain}", response_model=DomainExportResponse)
async def export_domain_data(
    domain: str,
    format: str = "json",
    include_evolution: bool = True,
    include_field_analysis: bool = True,
    include_compatibility: bool = True
):
    """
    Export comprehensive domain-specific data
    
    Generates structured export of domain evolution, field analysis,
    and compatibility data for research and documentation purposes.
    
    Requirements: 8.6
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Validate format
        valid_formats = ["json", "csv", "markdown"]
        if format not in valid_formats:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid format '{format}'. Valid formats: {valid_formats}"
            )
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions and prepare services
        versions = await skos_manager.get_all_versions()
        domain_evolution_analyzer.load_versions(versions)
        domain_compatibility_assessor.load_versions(versions)
        
        # Initialize export data structure
        export_data = {
            "domain": semantic_domain.value,
            "export_metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "export_format": format,
                "versions_included": [v.id for v in versions],
                "total_versions": len(versions),
                "exporter_version": "1.0.0"
            }
        }
        
        # Include domain evolution data
        if include_evolution:
            try:
                domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
                domain_evolution_analyzer.load_domain_evolutions([domain_evolution])
                
                evolution_data = await domain_evolution_analyzer.analyze_domain_evolution(semantic_domain)
                evolution_timeline = await domain_evolution_analyzer.generate_evolution_timeline(
                    semantic_domain, include_details=True
                )
                
                export_data["evolution_data"] = {
                    "domain_evolution": {
                        "evolution_entries": [
                            {
                                "version": entry.version,
                                "year": entry.year,
                                "changes": [
                                    {
                                        "change_type": change.change_type.value,
                                        "field_name": change.field_name,
                                        "semantic_impact": change.semantic_impact,
                                        "compatibility_impact": change.compatibility_impact.value,
                                        "previous_value": change.previous_value,
                                        "new_value": change.new_value
                                    }
                                    for change in entry.changes
                                ],
                                "semantic_notes": entry.semantic_notes or []
                            }
                            for entry in evolution_data.evolution_entries
                        ]
                    },
                    "evolution_timeline": evolution_timeline,
                    "field_evolution_map": evolution_data.field_evolution_map or {}
                }
            except ValueError:
                export_data["evolution_data"] = {"available": False, "reason": "No evolution data found"}
        
        # Include field analysis data
        if include_field_analysis:
            # Collect all fields for the domain
            all_domain_fields = []
            for version in versions:
                domain_fields = [f for f in version.field_definitions if f.semantic_domain == semantic_domain]
                all_domain_fields.extend(domain_fields)
            
            # Perform field grouping and analysis
            field_groups = semantic_field_grouper.group_fields_by_semantics(
                all_domain_fields, semantic_domain
            )
            domain_analysis = semantic_field_grouper.analyze_domain_specific_fields(
                semantic_domain, versions
            )
            field_categories = semantic_field_grouper.categorize_semantic_fields(
                all_domain_fields, semantic_domain
            )
            
            export_data["field_analysis"] = {
                "field_groups": [
                    {
                        "group_id": group.group_id,
                        "group_name": group.group_name,
                        "fields": group.fields,
                        "semantic_theme": group.semantic_theme,
                        "cohesion_score": group.cohesion_score,
                        "relationship_count": len(group.relationships)
                    }
                    for group in field_groups
                ],
                "domain_analysis": domain_analysis,
                "field_categories": field_categories,
                "analysis_summary": {
                    "total_fields": len(all_domain_fields),
                    "total_groups": len(field_groups),
                    "average_group_size": sum(len(g.fields) for g in field_groups) / len(field_groups) if field_groups else 0
                }
            }
        
        # Include compatibility data
        if include_compatibility:
            try:
                # Load domain evolutions for compatibility assessment
                try:
                    domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
                    domain_compatibility_assessor.load_domain_evolutions([domain_evolution])
                except ValueError:
                    pass
                
                # Create compatibility matrix for all versions
                compatibility_matrix = await domain_compatibility_assessor.create_domain_compatibility_matrix(
                    semantic_domain
                )
                
                # Get detailed compatibility assessments for key version pairs
                version_pairs = [('1966', '2020'), ('1979', '2020'), ('2000', '2020')]
                detailed_assessments = {}
                
                for from_ver, to_ver in version_pairs:
                    if from_ver in [v.id for v in versions] and to_ver in [v.id for v in versions]:
                        assessment = await domain_compatibility_assessor.assess_domain_compatibility(
                            semantic_domain, from_ver, to_ver, detailed_analysis=True
                        )
                        detailed_assessments[f"{from_ver}_to_{to_ver}"] = dict(assessment)
                
                export_data["compatibility_data"] = {
                    "compatibility_matrix": {
                        "domain": semantic_domain.value,
                        "compatibility_map": {
                            f"{from_ver}->{to_ver}": level.value if hasattr(level, 'value') else str(level)
                            for (from_ver, to_ver), level in compatibility_matrix.compatibility_map.items()
                        }
                    },
                    "detailed_assessments": detailed_assessments,
                    "compatibility_summary": {
                        "total_version_pairs": len(compatibility_matrix.compatibility_map),
                        "full_compatibility_pairs": len([
                            level for level in compatibility_matrix.compatibility_map.values()
                            if level == DomainCompatibilityLevel.FULL
                        ]),
                        "lossy_conversion_pairs": len([
                            assessment for assessment in detailed_assessments.values()
                            if assessment.get('is_lossy', False)
                        ])
                    }
                }
            except Exception as e:
                export_data["compatibility_data"] = {
                    "available": False, 
                    "reason": f"Compatibility analysis failed: {str(e)}"
                }
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return DomainExportResponse(
            success=True,
            domain=semantic_domain.value,
            export_data=export_data,
            export_format=format,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainExportResponse(
            success=False,
            domain=domain,
            error=str(e),
            processing_time_ms=processing_time
        )

# Domain Documentation Request/Response Models
class DomainDocumentationResponse(BaseModel):
    """Response model for domain documentation"""
    success: bool
    domain: str
    documentation: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class DomainListResponse(BaseModel):
    """Response model for available domains list"""
    success: bool
    domains: Optional[List[Dict[str, Any]]] = None
    total_domains: Optional[int] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


class DomainExamplesResponse(BaseModel):
    """Response model for domain-specific examples"""
    success: bool
    domain: str
    examples: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None


@router.get("/domains/{domain}/documentation", response_model=DomainDocumentationResponse)
async def get_domain_documentation(domain: str):
    """
    Get comprehensive documentation for a specific semantic domain
    
    Returns detailed documentation including domain description, field definitions,
    evolution history, and usage guidelines for the specified semantic domain.
    
    Requirements: 8.7
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions for comprehensive analysis
        versions = await skos_manager.get_all_versions()
        
        # Get domain definition and description
        domain_descriptions = {
            SemanticDomain.IDENTIFICATION_MARKING: {
                "name": "Identification & Marking",
                "description": "Ring numbers, schemes, metal rings, other marks, and verification systems used to identify individual birds.",
                "purpose": "Tracks the physical identification methods and marking systems used in bird ringing operations.",
                "key_concepts": ["Ring numbers", "Scheme codes", "Metal rings", "Other marks", "Verification"]
            },
            SemanticDomain.SPECIES: {
                "name": "Species Classification",
                "description": "Species codes, taxonomy, and identification systems for bird species classification.",
                "purpose": "Manages species identification using standardized taxonomic codes and classification systems.",
                "key_concepts": ["Species codes", "Taxonomy", "Finder identification", "Scheme identification"]
            },
            SemanticDomain.DEMOGRAPHICS: {
                "name": "Demographics",
                "description": "Age and sex classification systems for demographic analysis of bird populations.",
                "purpose": "Captures demographic characteristics essential for population studies and breeding analysis.",
                "key_concepts": ["Age classification", "Sex determination", "Demographic coding"]
            },
            SemanticDomain.TEMPORAL: {
                "name": "Temporal Information",
                "description": "Date and time formats and their evolution across EURING versions.",
                "purpose": "Records temporal aspects of ringing and recovery events for chronological analysis.",
                "key_concepts": ["Date formats", "Time recording", "Temporal evolution", "Event timing"]
            },
            SemanticDomain.SPATIAL: {
                "name": "Spatial Information",
                "description": "Coordinates, location accuracy, and geographic encoding systems.",
                "purpose": "Captures geographic location data for spatial analysis and migration studies.",
                "key_concepts": ["Coordinates", "Location accuracy", "Geographic encoding", "Spatial precision"]
            },
            SemanticDomain.BIOMETRICS: {
                "name": "Biometric Measurements",
                "description": "Wing, weight, bill, tarsus, fat, muscle, and moult measurements for morphological analysis.",
                "purpose": "Records physical measurements essential for species identification and condition assessment.",
                "key_concepts": ["Wing length", "Body weight", "Bill measurements", "Tarsus length", "Body condition"]
            },
            SemanticDomain.METHODOLOGY: {
                "name": "Methodology & Conditions",
                "description": "Capture methods, conditions, manipulation codes, and operational procedures.",
                "purpose": "Documents the methods and conditions under which ringing operations were conducted.",
                "key_concepts": ["Capture methods", "Operational conditions", "Manipulation codes", "Procedures"]
            }
        }
        
        domain_info = domain_descriptions.get(semantic_domain, {
            "name": semantic_domain.value.replace('_', ' ').title(),
            "description": f"Documentation for {semantic_domain.value} domain",
            "purpose": "Semantic domain for EURING code analysis",
            "key_concepts": []
        })
        
        # Collect field definitions across all versions
        field_definitions = {}
        for version in versions:
            version_fields = [f for f in version.field_definitions if f.semantic_domain == semantic_domain]
            field_definitions[version.id] = [
                {
                    "position": field.position,
                    "name": field.name,
                    "data_type": field.data_type,
                    "length": field.length,
                    "description": field.description,
                    "semantic_meaning": field.semantic_meaning,
                    "valid_values": field.valid_values,
                    "evolution_notes": field.evolution_notes
                }
                for field in version_fields
            ]
        
        # Get evolution history if available
        evolution_history = []
        try:
            domain_evolution = await skos_manager.get_domain_evolution(semantic_domain)
            evolution_history = [
                {
                    "version": entry.version,
                    "year": entry.year,
                    "changes_summary": f"{len(entry.changes)} changes",
                    "fields_added": entry.fields_added or [],
                    "fields_removed": entry.fields_removed or [],
                    "fields_modified": entry.fields_modified or [],
                    "semantic_notes": entry.semantic_notes or [],
                    "format_changes": entry.format_changes or []
                }
                for entry in domain_evolution.evolution_entries
            ]
        except ValueError:
            evolution_history = []
        
        # Get usage guidelines and best practices
        usage_guidelines = {
            SemanticDomain.IDENTIFICATION_MARKING: [
                "Always verify ring number format matches the expected scheme",
                "Check for consistency between scheme codes and ring formats",
                "Validate verification codes when present",
                "Consider ring readability and condition in data quality assessment"
            ],
            SemanticDomain.SPECIES: [
                "Use official species codes from recognized taxonomic authorities",
                "Distinguish between finder and scheme species identification",
                "Validate species codes against current taxonomic standards",
                "Consider subspecies identification when available"
            ],
            SemanticDomain.DEMOGRAPHICS: [
                "Apply age classification consistently within studies",
                "Document sex determination methods and confidence levels",
                "Consider seasonal variations in demographic characteristics",
                "Use standardized age and sex coding systems"
            ],
            SemanticDomain.TEMPORAL: [
                "Ensure date format consistency within datasets",
                "Account for timezone differences in temporal analysis",
                "Validate date ranges for biological plausibility",
                "Consider seasonal patterns in temporal data"
            ],
            SemanticDomain.SPATIAL: [
                "Verify coordinate system and datum consistency",
                "Assess location accuracy for spatial analysis requirements",
                "Consider coordinate precision in distance calculations",
                "Validate geographic coordinates for biological plausibility"
            ],
            SemanticDomain.BIOMETRICS: [
                "Apply measurement protocols consistently",
                "Consider measurement precision and accuracy",
                "Account for age and sex differences in biometric analysis",
                "Validate measurements against species-specific ranges"
            ],
            SemanticDomain.METHODOLOGY: [
                "Document capture methods for bias assessment",
                "Record environmental conditions affecting capture success",
                "Consider method-specific biases in data interpretation",
                "Maintain consistency in methodology coding"
            ]
        }.get(semantic_domain, [])
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Prepare comprehensive documentation
        documentation = {
            "domain_info": domain_info,
            "field_definitions": field_definitions,
            "evolution_history": evolution_history,
            "usage_guidelines": usage_guidelines,
            "statistics": {
                "total_versions": len(versions),
                "versions_with_domain": len([v for v in field_definitions.values() if v]),
                "total_fields_across_versions": sum(len(fields) for fields in field_definitions.values()),
                "evolution_entries": len(evolution_history)
            },
            "related_domains": [
                d.value for d in SemanticDomain 
                if d != semantic_domain and any(
                    field.semantic_domain == d 
                    for version in versions 
                    for field in version.field_definitions
                )
            ]
        }
        
        return DomainDocumentationResponse(
            success=True,
            domain=semantic_domain.value,
            documentation=documentation,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainDocumentationResponse(
            success=False,
            domain=domain,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/domains/list", response_model=DomainListResponse)
async def get_available_domains():
    """
    Get list of all available semantic domains
    
    Returns comprehensive information about all semantic domains available
    in the EURING system, including descriptions and field counts.
    
    Requirements: 8.7
    """
    start_time = datetime.now()
    
    try:
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions for analysis
        versions = await skos_manager.get_all_versions()
        
        # Domain information with descriptions
        domain_info = {
            SemanticDomain.IDENTIFICATION_MARKING: {
                "name": "Identification & Marking",
                "description": "Ring numbers, schemes, metal rings, other marks, and verification systems",
                "icon": "🏷️",
                "color": "#FF6B6B",
                "stability_score": 3,
                "complexity": "High"
            },
            SemanticDomain.SPECIES: {
                "name": "Species Classification", 
                "description": "Species codes, taxonomy, and identification systems",
                "icon": "🐦",
                "color": "#4ECDC4",
                "stability_score": 7,
                "complexity": "Medium"
            },
            SemanticDomain.DEMOGRAPHICS: {
                "name": "Demographics",
                "description": "Age and sex classification systems",
                "icon": "👥",
                "color": "#45B7D1",
                "stability_score": 6,
                "complexity": "Medium"
            },
            SemanticDomain.TEMPORAL: {
                "name": "Temporal Information",
                "description": "Date and time formats and their evolution",
                "icon": "⏰",
                "color": "#FFA07A",
                "stability_score": 2,
                "complexity": "High"
            },
            SemanticDomain.SPATIAL: {
                "name": "Spatial Information",
                "description": "Coordinates, location accuracy, and geographic encoding",
                "icon": "🌍",
                "color": "#98D8C8",
                "stability_score": 1,
                "complexity": "Very High"
            },
            SemanticDomain.BIOMETRICS: {
                "name": "Biometric Measurements",
                "description": "Wing, weight, bill, tarsus, fat, muscle, and moult measurements",
                "icon": "📏",
                "color": "#F7DC6F",
                "stability_score": 4,
                "complexity": "High"
            },
            SemanticDomain.METHODOLOGY: {
                "name": "Methodology & Conditions",
                "description": "Capture methods, conditions, manipulation codes, and procedures",
                "icon": "🔬",
                "color": "#BB8FCE",
                "stability_score": 5,
                "complexity": "Medium"
            }
        }
        
        # Calculate statistics for each domain
        domains_list = []
        for semantic_domain in SemanticDomain:
            info = domain_info.get(semantic_domain, {})
            
            # Count fields across versions
            field_counts = {}
            total_fields = 0
            for version in versions:
                version_fields = [f for f in version.field_definitions if f.semantic_domain == semantic_domain]
                field_counts[version.id] = len(version_fields)
                total_fields += len(version_fields)
            
            # Check for evolution data
            has_evolution_data = False
            try:
                await skos_manager.get_domain_evolution(semantic_domain)
                has_evolution_data = True
            except ValueError:
                pass
            
            # Calculate presence across versions
            versions_with_domain = len([count for count in field_counts.values() if count > 0])
            
            domain_entry = {
                "domain": semantic_domain.value,
                "name": info.get("name", semantic_domain.value.replace('_', ' ').title()),
                "description": info.get("description", f"Domain for {semantic_domain.value}"),
                "icon": info.get("icon", "📊"),
                "color": info.get("color", "#95A5A6"),
                "stability_score": info.get("stability_score", 5),
                "complexity": info.get("complexity", "Medium"),
                "statistics": {
                    "total_fields": total_fields,
                    "field_counts_by_version": field_counts,
                    "versions_present": versions_with_domain,
                    "total_versions": len(versions),
                    "coverage_percentage": round((versions_with_domain / len(versions)) * 100, 1) if versions else 0
                },
                "has_evolution_data": has_evolution_data,
                "api_endpoints": [
                    f"/api/euring/domains/{semantic_domain.value}/documentation",
                    f"/api/euring/domains/{semantic_domain.value}/evolution",
                    f"/api/euring/domains/{semantic_domain.value}/fields",
                    f"/api/euring/domains/{semantic_domain.value}/examples"
                ]
            }
            
            domains_list.append(domain_entry)
        
        # Sort by stability score (descending) for better UX
        domains_list.sort(key=lambda x: x["stability_score"], reverse=True)
        
        # Calculate overall statistics
        total_domains = len(domains_list)
        domains_with_evolution = len([d for d in domains_list if d["has_evolution_data"]])
        average_stability = sum(d["stability_score"] for d in domains_list) / total_domains if total_domains else 0
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return DomainListResponse(
            success=True,
            domains=domains_list,
            total_domains=total_domains,
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainListResponse(
            success=False,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/domains/{domain}/examples", response_model=DomainExamplesResponse)
async def get_domain_examples(domain: str):
    """
    Get domain-specific examples and use cases
    
    Returns practical examples of EURING strings highlighting the specified domain,
    including field explanations and common patterns.
    
    Requirements: 8.7
    """
    start_time = datetime.now()
    
    try:
        # Validate domain
        try:
            semantic_domain = SemanticDomain(domain.lower())
        except ValueError:
            valid_domains = [d.value for d in SemanticDomain]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid domain '{domain}'. Valid domains: {valid_domains}"
            )
        
        # Initialize services
        await skos_manager.load_version_model()
        
        # Load versions for analysis
        versions = await skos_manager.get_all_versions()
        
        # Define example EURING strings for each version
        example_strings = {
            "1966": "5320 TA12345 3 11022023 5215N 01325E 10 2 050 0115 0750",
            "1979": "05320ISA12345 099200501199505215215N01325E10321--0500115--075010--001090------",
            "2000": "IABA0SA...7285004ZZ1187011870H0ZUMM55U-----0105200600600IA13+452409+009033908200400000---00086",
            "2020": "05320|ISA12345|0|09920|3|2|20230521|1430|52.25412|-1.34521|1|10|01|0|0|135.5|19.5|4|2|0|0|2",
            "2020_official": "05320|ISA12345|0|09920|3|2|20230521|1430|52.25412|-1.34521|1|10|01|0|0|135.5|19.5|4|2|0|0|2"
        }
        
        # Domain-specific example explanations
        domain_examples = {
            SemanticDomain.IDENTIFICATION_MARKING: {
                "focus_description": "Ring numbers, scheme codes, and marking systems",
                "highlighted_fields": ["ring_number", "scheme", "metal_ring", "other_marks", "verification"],
                "common_patterns": [
                    "Ring numbers evolve from simple numeric to complex alphanumeric formats",
                    "Scheme codes become more sophisticated with country and organization identifiers",
                    "Verification systems introduced in modern versions for data quality"
                ],
                "interpretation_notes": [
                    "Ring number format indicates the ringing scheme and period",
                    "Scheme codes help identify the organization responsible for ringing",
                    "Metal ring and other marks provide additional identification methods"
                ]
            },
            SemanticDomain.SPECIES: {
                "focus_description": "Species identification codes and taxonomic classification",
                "highlighted_fields": ["species_code", "finder_species", "scheme_species"],
                "common_patterns": [
                    "Species codes expand from 4 to 5 digits over time",
                    "Modern versions separate finder vs scheme species identification",
                    "Codes align with international taxonomic standards"
                ],
                "interpretation_notes": [
                    "Species codes follow standardized taxonomic numbering systems",
                    "Finder identification may differ from official scheme identification",
                    "Code precision improves with taxonomic knowledge advancement"
                ]
            },
            SemanticDomain.DEMOGRAPHICS: {
                "focus_description": "Age and sex classification for population analysis",
                "highlighted_fields": ["age", "sex", "finder_age", "scheme_age", "finder_sex", "scheme_sex"],
                "common_patterns": [
                    "Age coding evolves from numeric (1-9) to alphanumeric systems",
                    "Sex determination becomes more sophisticated with M/F/U categories",
                    "Dual finder/scheme approach in modern versions"
                ],
                "interpretation_notes": [
                    "Age codes represent standardized life stage classifications",
                    "Sex determination confidence varies by species and season",
                    "Demographic data essential for population studies"
                ]
            },
            SemanticDomain.TEMPORAL: {
                "focus_description": "Date and time recording systems",
                "highlighted_fields": ["date", "time", "first_date", "current_date"],
                "common_patterns": [
                    "Date formats change dramatically: DDMMYYYY → DDMMYY → encoded → YYYYMMDD",
                    "Time recording introduced in 2020 version (HHMM format)",
                    "Temporal fields eventually removed in official SKOS version"
                ],
                "interpretation_notes": [
                    "Date format evolution reflects technological and standardization changes",
                    "Time precision varies by operational requirements",
                    "Temporal data critical for migration and behavior studies"
                ]
            },
            SemanticDomain.SPATIAL: {
                "focus_description": "Geographic coordinates and location accuracy",
                "highlighted_fields": ["latitude", "longitude", "coordinate_accuracy", "place_code"],
                "common_patterns": [
                    "Coordinate systems evolve: degrees/minutes → encoded → decimal degrees",
                    "Accuracy coding remains consistent across versions",
                    "Complete removal of spatial data in official SKOS version"
                ],
                "interpretation_notes": [
                    "Coordinate precision affects spatial analysis accuracy",
                    "Location accuracy codes indicate measurement reliability",
                    "Geographic data essential for migration route analysis"
                ]
            },
            SemanticDomain.BIOMETRICS: {
                "focus_description": "Physical measurements and body condition",
                "highlighted_fields": ["wing_length", "weight", "bill_length", "tarsus_length", "fat_score", "muscle_score"],
                "common_patterns": [
                    "Measurement precision evolves: integer → decimal → coded values",
                    "Body condition scoring (fat, muscle, moult) introduced in 2020",
                    "Measurement units standardized (mm for length, g for weight)"
                ],
                "interpretation_notes": [
                    "Biometric data essential for species identification and condition assessment",
                    "Measurement precision affects morphological analysis accuracy",
                    "Body condition scores indicate individual fitness and health"
                ]
            },
            SemanticDomain.METHODOLOGY: {
                "focus_description": "Capture methods and operational conditions",
                "highlighted_fields": ["capture_method", "condition", "manipulation", "circumstances"],
                "common_patterns": [
                    "Capture method codes become more detailed over time",
                    "Condition codes remain relatively stable across versions",
                    "Manipulation codes use priority-based selection in modern versions"
                ],
                "interpretation_notes": [
                    "Capture method affects data interpretation and bias assessment",
                    "Condition codes indicate bird health and capture circumstances",
                    "Methodology data essential for standardizing research protocols"
                ]
            }
        }
        
        domain_info = domain_examples.get(semantic_domain, {
            "focus_description": f"Examples for {semantic_domain.value} domain",
            "highlighted_fields": [],
            "common_patterns": [],
            "interpretation_notes": []
        })
        
        # Generate examples for each version
        version_examples = []
        for version in versions:
            if version.id in example_strings:
                # Get domain-specific fields for this version
                domain_fields = [f for f in version.field_definitions if f.semantic_domain == semantic_domain]
                
                if domain_fields:  # Only include versions that have fields in this domain
                    example_string = example_strings[version.id]
                    
                    # Parse the example string to highlight domain-specific parts
                    field_highlights = []
                    for field in domain_fields:
                        field_highlights.append({
                            "position": field.position,
                            "name": field.name,
                            "description": field.description,
                            "semantic_meaning": field.semantic_meaning,
                            "data_type": field.data_type,
                            "length": field.length
                        })
                    
                    version_examples.append({
                        "version": version.id,
                        "version_name": version.name,
                        "year": version.year,
                        "example_string": example_string,
                        "format": version.format_specification.field_separator or "space_separated" if version.id == "1966" else "fixed_length",
                        "domain_fields": field_highlights,
                        "field_count": len(domain_fields),
                        "total_length": len(example_string)
                    })
        
        # Generate use cases and scenarios
        use_cases = {
            SemanticDomain.IDENTIFICATION_MARKING: [
                {
                    "title": "Ring Number Validation",
                    "description": "Verify ring number format matches expected scheme",
                    "example": "Ring 'TA12345' indicates scheme 'TA' with 5-digit number"
                },
                {
                    "title": "Scheme Identification",
                    "description": "Identify ringing organization from scheme codes",
                    "example": "Scheme '5320' indicates specific national ringing program"
                }
            ],
            SemanticDomain.SPECIES: [
                {
                    "title": "Species Code Lookup",
                    "description": "Convert species codes to taxonomic names",
                    "example": "Code '09920' represents a specific bird species"
                },
                {
                    "title": "Taxonomic Validation",
                    "description": "Verify species codes against current taxonomy",
                    "example": "Check if species code is valid for the time period"
                }
            ],
            SemanticDomain.DEMOGRAPHICS: [
                {
                    "title": "Age Structure Analysis",
                    "description": "Analyze population age distribution",
                    "example": "Age code '3' indicates adult bird in breeding condition"
                },
                {
                    "title": "Sex Ratio Studies",
                    "description": "Calculate sex ratios for population studies",
                    "example": "Sex code '2' indicates female bird"
                }
            ],
            SemanticDomain.TEMPORAL: [
                {
                    "title": "Migration Timing",
                    "description": "Analyze seasonal migration patterns",
                    "example": "Date '20230521' indicates spring migration period"
                },
                {
                    "title": "Capture Timing",
                    "description": "Study daily activity patterns",
                    "example": "Time '1430' indicates afternoon capture"
                }
            ],
            SemanticDomain.SPATIAL: [
                {
                    "title": "Migration Routes",
                    "description": "Map bird movement patterns",
                    "example": "Coordinates 52.25412, -1.34521 show precise location"
                },
                {
                    "title": "Habitat Analysis",
                    "description": "Study habitat preferences by location",
                    "example": "Location accuracy '1' indicates GPS precision"
                }
            ],
            SemanticDomain.BIOMETRICS: [
                {
                    "title": "Morphological Analysis",
                    "description": "Study size variation within species",
                    "example": "Wing length 135.5mm indicates adult male characteristics"
                },
                {
                    "title": "Body Condition Assessment",
                    "description": "Evaluate individual fitness and health",
                    "example": "Weight 19.5g with fat score 4 indicates good condition"
                }
            ],
            SemanticDomain.METHODOLOGY: [
                {
                    "title": "Capture Bias Assessment",
                    "description": "Account for method-specific biases",
                    "example": "Method '10' indicates mist net capture"
                },
                {
                    "title": "Data Quality Control",
                    "description": "Validate capture conditions and procedures",
                    "example": "Condition '01' indicates normal capture circumstances"
                }
            ]
        }.get(semantic_domain, [])
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Prepare comprehensive examples response
        examples = {
            "domain_info": {
                "domain": semantic_domain.value,
                "name": semantic_domain.value.replace('_', ' ').title(),
                "focus_description": domain_info["focus_description"],
                "highlighted_fields": domain_info["highlighted_fields"],
                "common_patterns": domain_info["common_patterns"],
                "interpretation_notes": domain_info["interpretation_notes"]
            },
            "version_examples": version_examples,
            "use_cases": use_cases,
            "statistics": {
                "versions_with_examples": len(version_examples),
                "total_versions": len(versions),
                "total_domain_fields": sum(ex["field_count"] for ex in version_examples),
                "example_coverage": round((len(version_examples) / len(versions)) * 100, 1) if versions else 0
            },
            "related_endpoints": [
                f"/api/euring/domains/{semantic_domain.value}/documentation",
                f"/api/euring/domains/{semantic_domain.value}/evolution",
                f"/api/euring/domains/{semantic_domain.value}/fields"
            ]
        }
        
        return DomainExamplesResponse(
            success=True,
            domain=semantic_domain.value,
            examples=examples,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return DomainExamplesResponse(
            success=False,
            domain=domain,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/versions/{version}/field/{field_name}/lookup", response_model=LookupTableResponse)
async def get_field_lookup_table(version: str, field_name: str):
    """
    Get lookup table for a specific field in a version
    
    Returns predefined value lists with code-meaning mappings for fields
    that have constrained valid values (e.g., species codes, scheme codes).
    
    Requirements: Lookup table functionality for EURING field values
    """
    start_time = datetime.now()
    
    try:
        # Validate version
        valid_versions = ['1966', '1979', '2000', '2020']
        if version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version: {version}")
        
        # Get lookup table
        lookup_table = await lookup_table_service.get_field_lookup_table(field_name, version)
        
        if not lookup_table:
            raise HTTPException(status_code=404, detail=f"No lookup table found for field '{field_name}' in version {version}")
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return LookupTableResponse(
            success=True,
            field_name=field_name,
            version=version,
            lookup_table=lookup_table,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return LookupTableResponse(
            success=False,
            field_name=field_name,
            version=version,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/versions/{version}/lookups", response_model=AllLookupTablesResponse)
async def get_all_lookup_tables(version: str):
    """
    Get all available lookup tables for a version
    
    Returns all fields that have predefined value lists with their
    code-meaning mappings for the specified EURING version.
    
    Requirements: Complete lookup table overview for version
    """
    start_time = datetime.now()
    
    try:
        # Validate version
        valid_versions = ['1966', '1979', '2000', '2020']
        if version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version: {version}")
        
        # Get all lookup tables
        lookup_tables = await lookup_table_service.get_all_field_lookups(version)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return AllLookupTablesResponse(
            success=True,
            version=version,
            lookup_tables=lookup_tables,
            total_tables=len(lookup_tables),
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return AllLookupTablesResponse(
            success=False,
            version=version,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.put("/versions/{version}/field/{field_name}/lookup", response_model=LookupTableResponse)
async def update_field_lookup_table(version: str, field_name: str, request: LookupTableUpdateRequest):
    """
    Update lookup table for a specific field
    
    Allows editing of predefined value lists and their meanings.
    Changes are saved to the SKOS repository for persistence.
    
    Requirements: Editable lookup tables for field values
    """
    start_time = datetime.now()
    
    try:
        # Validate version
        valid_versions = ['1966', '1979', '2000', '2020']
        if version not in valid_versions:
            raise HTTPException(status_code=400, detail=f"Invalid version: {version}")
        
        # Validate request
        if request.field_name != field_name or request.version != version:
            raise HTTPException(status_code=400, detail="Field name and version in request must match URL parameters")
        
        # Update lookup table
        success = await lookup_table_service.update_field_lookup_table(field_name, version, request.lookup_data)
        
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to update lookup table for field '{field_name}'")
        
        # Get updated lookup table
        updated_lookup = await lookup_table_service.get_field_lookup_table(field_name, version)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return LookupTableResponse(
            success=True,
            field_name=field_name,
            version=version,
            lookup_table=updated_lookup,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        return LookupTableResponse(
            success=False,
            field_name=field_name,
            version=version,
            error=str(e),
            processing_time_ms=processing_time
        )


@router.get("/health")
async def health_check():
    """
    Health check endpoint
    
    Returns the health status of the EURING API services.
    """
    try:
        # Test recognition engine
        test_string = "5320 TA12345 3 11022023 5215N 01325E 10 2 050 0115 0750"
        recognition_result = await recognition_engine.recognize_version(test_string)
        recognition_healthy = recognition_result.detected_version.id == 'euring_1966' if recognition_result.detected_version else False
        
        # Test conversion service
        conversion_result = conversion_service.convert_semantic(test_string, '1966', '2020')
        conversion_healthy = conversion_result.get('success', False)
        
        return {
            "status": "healthy" if recognition_healthy and conversion_healthy else "degraded",
            "services": {
                "recognition_engine": "healthy" if recognition_healthy else "error",
                "conversion_service": "healthy" if conversion_healthy else "error",
                "semantic_converter": "healthy"
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }