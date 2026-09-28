# Run by the Oracle image at every start — gvenzl/oracle-free sources the
# scripts of /container-entrypoint-startdb.d, where docker-compose.yml and
# CI mount this directory; hence the subshell, and no exit. For
# tests/test_oracle_connector.py only.
#
# The image serves TCP on 1521 and no TLS: this adds TCPS on 2484, with the
# test wallet beside this file — a self-signed certificate, CN=leka-oracle,
# for this container and nothing else; the connector verifies no
# certificate. The slim image has no Java, and so no orapki: the wallet was
# made once with Oracle's PKI jars from Maven Central
# (com.oracle.database.security:oraclepki 23.26.3.0.0, osdt_core and
# osdt_cert 21.23.0.0) in an eclipse-temurin:21-jre container:
#   java -cp oraclepki.jar:osdt_core.jar:osdt_cert.jar \
#     oracle.security.pki.textui.OraclePKITextUI wallet create -wallet w \
#     -pwd Leka-wallet-1 -auto_login
#   … wallet add -wallet w -pwd Leka-wallet-1 -dn CN=leka-oracle \
#     -keysize 2048 -self_signed -validity 3650 -sign_alg sha256
(
  set -euo pipefail
  here="$(dirname "${BASH_SOURCE[0]}")"
  wallet=/opt/oracle/wallet
  admin="$ORACLE_HOME/network/admin"
  mkdir -p "$wallet"
  cp "$here/wallet/cwallet.sso" "$here/wallet/ewallet.p12" "$wallet/"
  cat > "$admin/listener.ora" <<LISTENER
LISTENER =
  (DESCRIPTION_LIST =
    (DESCRIPTION =
      (ADDRESS = (PROTOCOL = IPC)(KEY = EXTPROC_FOR_FREE))
      (ADDRESS = (PROTOCOL = TCP)(HOST = 0.0.0.0)(PORT = 1521))
      (ADDRESS = (PROTOCOL = TCPS)(HOST = 0.0.0.0)(PORT = 2484))
    )
  )
WALLET_LOCATION = (SOURCE = (METHOD = FILE)(METHOD_DATA = (DIRECTORY = $wallet)))
SSL_CLIENT_AUTHENTICATION = FALSE
DEFAULT_SERVICE_LISTENER = FREE
LISTENER
  grep -q WALLET_LOCATION "$admin/sqlnet.ora" || cat >> "$admin/sqlnet.ora" <<SQLNET
WALLET_LOCATION = (SOURCE = (METHOD = FILE)(METHOD_DATA = (DIRECTORY = $wallet)))
SSL_CLIENT_AUTHENTICATION = FALSE
SQLNET
  lsnrctl stop > /dev/null 2>&1 || true
  lsnrctl start > /dev/null
  echo "ALTER SYSTEM REGISTER;" | sqlplus -s / as sysdba > /dev/null
  echo "TLS listening on 2484"
)
