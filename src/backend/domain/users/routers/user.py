from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.domain.users.schemas.user import UserCreate, UserLogin
from backend.domain.users.services.user import UserService

router = APIRouter(prefix="/auth", tags=["AUTH"])

# 회원가입 및 로그인 기능 구현 코드
# 보통 회원가입은 데이터를 생성하는 POST, 로그인은 인증 정보를 검증하고 토큰 등을 발급하는 POST 요청으로 처리하는 것이 일반적이므로,

# 의존성 주입(Dependency Injection)이란 무엇인가요?
# 의존성 주입(Dependency Injection, DI)은 소프트웨어 설계 패턴 중 하나로, 객체 간의 의존성을 외부에서 주입하여 결합도를 낮추고 유연성을 높이는 방법입니다.
# FastAPI에서는 의존성 주입을 통해 요청 처리 함수에 필요한 객체나 데이터를 자동으로 제공할 수 있습니다.
# 예를 들어, 데이터베이스 세션, 인증 정보, 설정 값 등을 요청 처리 함수에 주입하여 코드의 재사용성과 테스트 용이성을 높일 수 있습니다.

# 쉬운 비유: 내가 직접 연필을 만들어서 글을 쓰는 게 아니라, 필요하라 때 연필을 책상 위에 꽂아주는(주입해 주는) 것입니다.
# 프로그래밍에서의 의미: 어떤 기능을 수행하기 위해 필요한 부품(객체나 데이터)을, 내부에서 직접 만들지 않고 외부에서 만들어서 건네받아 사용하는 방식을 말합니다.

# 왜 의존성 주입이 필요한가요?
# 1. 결합도 감소: 의존성 주입을 사용하면 클래스나 함수가 특정 구현에 직접 의존하지 않고, 외부에서 필요한 객체를 주입받기 때문에 결합도가 낮아집니다. 이는 코드의 유지보수성과 확장성을 높이는 데 도움이 됩니다.
# 2. 테스트 용이성: 의존성 주입을 사용하면 테스트 시 실제 구현 대신 모의 객체(Mock Object)를 주입하여 테스트할 수 있습니다. 이는 단위 테스트(Unit Test)를 작성할 때 유용합니다.
# 3. 유연성 향상: 의존성 주입을 통해 다양한 구현체를 주입할 수 있으므로, 코드의 유연성이 향상됩니다. 예를 들어, 데이터베이스 연결을 변경하거나, 다른 인증 방식을 적용하는 등의 작업이 용이해집니다.
#    라우터는 "손님(클라이언트)의 요청을 받고 응답을 주는 일"에만 집중합니다.
#    회원가입 검증이나 DB 저장 같은 복잡한 비즈니스 로직은 서비스(UserService)가 전담합니다.
#    코드가 각자의 역할만 하므로 훨씬 깔끔해집니다.

# FastAPI에서 의존성 주입을 사용하는 방법은 다음과 같습니다.
# 1. Depends를 사용하여 의존성을 주입합니다.
# 2. 의존성을 주입받는 함수나 클래스에서 필요한 객체를 매개변수로 선언합니다.
# 3. FastAPI는 요청이 들어올 때 해당 의존성을 자동으로 생성하고 주입합니다.
# 함수의 파라미터에 user_service: UserService = Depends(get_user_service)라고 적어두면,
# FastAPI가 라우터 함수를 실행하기 직전에 알아서 get_user_service() 함수를 실행시키고,
# 그 결과로 만들어진 UserService 객체를 파라미터에 쏙 집어넣어 줍니다.

# 장점 : 개발자가 직접 service = UserService()라고 객체를 생성할 필요가 없습니다.
# Depends는 단순히 서비스 객체뿐만 아니라, DB 연결 세션, 로그인한 유저 정보 확인(인증), 권한 체크 등 반복되는 공통 기능을 모듈화해서 가져다 쓸 때 진가가 발휘됩니다.
# (예: current_user = Depends(get_current_user))


def get_user_service(db: Session = Depends(get_db)):
    # UserService 객체를 생성하고 반환하는 함수
    return UserService(db)


# FastAPOI에서 라우터 함수에 의존성을 주입하는 방법은 Depends를 사용하는 것입니다.
# FastAPI야, signUp 함수를 실행하기 전에 get_user_service() 함수를 호출해서 UserService 객체를 만들어서 signUp 함수의 user_service 매개변수에 전달해줘.
@router.post("/sign-up", status_code=status.HTTP_201_CREATED)
def signUp(body: UserCreate, user_service: UserService = Depends(get_user_service)):
    # 회원가입 API
    # - 클라이언트가 보낸 데이터는 UserCreate DTO를 통해 자동으로 검증됩니다.
    # - UserService의 sign_up 메서드를 호출하여 회원가입 로직을 처리합니다.
    return user_service.sign_up(body)


@router.post("/sign-in")
def signIn(body: UserLogin, user_service: UserService = Depends(get_user_service)):
    # 로그인 API
    # - 클라이언트가 보낸 데이터는 UserLogin DTO를 통해 자동으로 검증됩니다.
    # - UserService의 sign_in 메서드를 호출하여 로그인 로직을 처리합니다.
    return user_service.sign_in(body)
